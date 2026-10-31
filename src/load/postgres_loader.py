"""PostgreSQL loader module using SQLAlchemy.

Bulk loads go through ``COPY ... FROM STDIN`` into a temporary table that is
then merged into the target with a single ``INSERT ... ON CONFLICT``. A COPY
streams one text block per batch instead of issuing one ``INSERT`` per row,
which is what made the 330 MB calendar load slow.
"""

import csv
import io
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import QueuePool

from src.config import get_config
from src.models import CalendarRaw, ListingRaw
from src.models.calendar import CALENDAR_FIELDS
from src.models.listing import LISTING_FIELDS

logger = logging.getLogger(__name__)

#: Conflict key of ``raw.listings``.
LISTINGS_CONFLICT_COLS: tuple[str, ...] = ("id",)

#: Conflict key of ``raw.calendar``.
CALENDAR_CONFLICT_COLS: tuple[str, ...] = ("listing_id", "date")

#: Columns excluded from the ``DO UPDATE SET`` clause of an upsert.
_NON_UPDATABLE = frozenset({"loaded_at"})


class PostgresLoader:
    """Loads data into PostgreSQL using SQLAlchemy."""

    def __init__(self, config_path: Path | None = None):
        self.config = get_config(config_path)
        self.engine: Engine | None = None
        self.SessionLocal: sessionmaker[Session] | None = None
        self.sql_dir = Path(__file__).parent.parent.parent / "sql"
        self.use_copy = self.config.pipeline.use_copy

    def connect(self) -> None:
        """Create database engine and session factory."""
        if self.engine is None:
            self.engine = create_engine(
                self.config.database.url,
                # A small pool keeps the connection alive across batches instead
                # of paying a TCP + auth handshake for every 100k rows.
                poolclass=QueuePool,
                pool_size=5,
                max_overflow=5,
                pool_pre_ping=True,
                echo=False,
            )
            self.SessionLocal = sessionmaker(
                bind=self.engine, autocommit=False, autoflush=False
            )
            logger.info("Database connection established")

    def disconnect(self) -> None:
        """Close database connections."""
        if self.engine:
            self.engine.dispose()
            self.engine = None
            self.SessionLocal = None
            logger.info("Database connection closed")

    @contextmanager
    def session(self) -> Iterator[Session]:
        """Provide a transactional scope around a series of operations."""
        if self.SessionLocal is None:
            self.connect()
        session_factory = self.SessionLocal
        assert session_factory is not None  # set by connect() above
        session = session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def execute_sql_file(self, sql_path: str) -> None:
        """Execute a SQL file."""
        with open(sql_path) as f:
            sql = f.read()

        with self.session() as session:
            # Split by semicolon and execute each statement
            statements = [s.strip() for s in sql.split(";") if s.strip()]
            for stmt in statements:
                if stmt:
                    session.execute(text(stmt))
            logger.info(f"Executed SQL file: {sql_path}")

    # ------------------------------------------------------------------
    # Bulk load helpers
    # ------------------------------------------------------------------

    def _upsert_sql(
        self,
        table: str,
        columns: list[str],
        conflict_cols: tuple[str, ...],
    ) -> str:
        """Build the ``INSERT ... SELECT ... ON CONFLICT`` merge statement."""
        update_cols = [
            c for c in columns if c not in conflict_cols and c not in _NON_UPDATABLE
        ]
        assignments = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_cols)
        assignments += ", loaded_at = NOW()"
        return (
            f"INSERT INTO {table} ({', '.join(columns)}) "
            f"SELECT {', '.join(columns)} FROM tmp_load "
            f"ON CONFLICT ({', '.join(conflict_cols)}) DO UPDATE SET {assignments}"
        )

    def _copy_dataframe(
        self,
        df: pd.DataFrame,
        table: str,
        conflict_cols: tuple[str, ...],
    ) -> int:
        """Stream ``df`` into ``table`` via COPY into a temp table, then merge."""
        columns = list(df.columns)
        buffer = io.StringIO()
        df.to_csv(
            buffer,
            index=False,
            header=False,
            na_rep="",
            quoting=csv.QUOTE_MINIMAL,
            lineterminator="\n",
        )
        buffer.seek(0)

        copy_sql = (
            f"COPY tmp_load ({', '.join(columns)}) FROM STDIN "
            f"WITH (FORMAT csv, NULL '')"
        )
        upsert_sql = self._upsert_sql(table, columns, conflict_cols)

        assert self.engine is not None
        with self.engine.begin() as conn:
            conn.execute(
                text(f"CREATE TEMP TABLE tmp_load (LIKE {table}) ON COMMIT DROP")
            )
            raw = conn.connection
            cursor = raw.cursor()
            try:
                cursor.copy_expert(copy_sql, buffer)
            finally:
                cursor.close()
            conn.execute(text(upsert_sql))

        return len(df)

    def _insert_dataframe(
        self,
        df: pd.DataFrame,
        table: str,
        conflict_cols: tuple[str, ...],
    ) -> int:
        """Fallback path: row-wise parameterized upsert (no COPY)."""
        columns = list(df.columns)
        placeholders = ", ".join(f":{col}" for col in columns)
        update_cols = [
            c for c in columns if c not in conflict_cols and c not in _NON_UPDATABLE
        ]
        assignments = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_cols)
        assignments += ", loaded_at = NOW()"
        sql = (
            f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders}) "
            f"ON CONFLICT ({', '.join(conflict_cols)}) DO UPDATE SET {assignments}"
        )

        records: list[dict[str, Any]] = df.to_dict(orient="records")
        with self.session() as session:
            session.execute(text(sql), records)

        return len(records)

    def _load(
        self,
        df: pd.DataFrame,
        table: str,
        conflict_cols: tuple[str, ...],
        source_file: str,
        label: str,
    ) -> int:
        if df.empty:
            return 0

        df = df.copy()
        df["source_file"] = source_file

        if self.use_copy:
            loaded = self._copy_dataframe(df, table, conflict_cols)
        else:
            loaded = self._insert_dataframe(df, table, conflict_cols)

        logger.info(f"Loaded {loaded} {label} into {table}")
        return loaded

    # ------------------------------------------------------------------
    # Public load API
    # ------------------------------------------------------------------

    def load_listings_df(self, df: pd.DataFrame, source_file: str) -> int:
        """Load a normalized listings DataFrame into ``raw.listings``."""
        return self._load(
            df, "raw.listings", LISTINGS_CONFLICT_COLS, source_file, "listings"
        )

    def load_calendar_df(self, df: pd.DataFrame, source_file: str) -> int:
        """Load a normalized calendar DataFrame into ``raw.calendar``."""
        return self._load(
            df, "raw.calendar", CALENDAR_CONFLICT_COLS, source_file, "calendar records"
        )

    def load_listings_raw(self, listings: list[ListingRaw], source_file: str) -> int:
        """Load validated ``ListingRaw`` models into ``raw.listings``."""
        if not listings:
            return 0
        df = pd.DataFrame(
            [m.model_dump(by_alias=True) for m in listings],
            columns=list(LISTING_FIELDS),
        )
        return self.load_listings_df(df, source_file)

    def load_calendar_raw(self, calendar: list[CalendarRaw], source_file: str) -> int:
        """Load validated ``CalendarRaw`` models into ``raw.calendar``."""
        if not calendar:
            return 0
        df = pd.DataFrame(
            [m.model_dump(by_alias=True) for m in calendar],
            columns=list(CALENDAR_FIELDS),
        )
        return self.load_calendar_df(df, source_file)

    # ------------------------------------------------------------------
    # Schema / transform helpers
    # ------------------------------------------------------------------

    def run_ddl(self) -> None:
        """Create all schemas and tables from the DDL scripts."""
        logger.info("Running DDL scripts...")
        self.execute_sql_file(str(self.sql_dir / "01_ddl_raw.sql"))
        self.execute_sql_file(str(self.sql_dir / "02_ddl_staging.sql"))
        self.execute_sql_file(str(self.sql_dir / "03_ddl_marts.sql"))
        logger.info("DDL scripts completed")

    def run_transform_staging(self) -> None:
        """Run raw -> staging transformation."""
        self.execute_sql_file(str(self.sql_dir / "04_transform_staging.sql"))
        logger.info("Completed raw -> staging transformation")

    def run_transform_marts(self) -> None:
        """Run staging -> marts transformation."""
        self.execute_sql_file(str(self.sql_dir / "05_transform_marts.sql"))
        logger.info("Completed staging -> marts transformation")

    def run_all_transforms(self) -> None:
        """Run all transformation steps."""
        self.run_transform_staging()
        self.run_transform_marts()

    def get_row_count(self, table: str, schema: str = "raw") -> int:
        """Get row count for a table."""
        with self.session() as session:
            result = session.execute(text(f"SELECT COUNT(*) FROM {schema}.{table}"))
            return result.scalar() or 0

    def truncate_raw_tables(self) -> None:
        """Truncate raw tables (for full reload)."""
        with self.session() as session:
            session.execute(text("TRUNCATE TABLE raw.calendar, raw.listings CASCADE"))
            logger.info("Truncated raw tables")


def get_loader(config_path: Path | None = None) -> PostgresLoader:
    """Factory function to create a PostgresLoader."""
    return PostgresLoader(config_path)
