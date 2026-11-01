"""Main ETL pipeline orchestration for Airbnb Occupancy Analytics."""

import argparse
import logging
import sys
from pathlib import Path

from src.config import AppConfig, get_config, setup_logging
from src.extract import make_extractor
from src.load.postgres_loader import PostgresLoader

logger = logging.getLogger(__name__)


class ETLPipeline:
    """Orchestrates the complete ETL pipeline."""

    def __init__(self, config_path: Path | None = None):
        self.config: AppConfig = get_config(config_path)
        setup_logging(self.config)
        self.extractor = make_extractor(config_path)
        self.loader = PostgresLoader(config_path)

    def setup_database(self) -> None:
        """Create database schema and tables."""
        logger.info("Setting up database schema...")
        self.loader.run_ddl()
        logger.info("Database schema ready")

    def load_raw_data(self) -> None:
        """Extract CSV data and load into raw tables.

        Each extractor batch is already a normalized DataFrame, so it is piped
        straight into the loader without any per-row model construction.
        """
        logger.info("Starting raw data load...")

        # Load listings
        listings_count = 0
        for batch in self.extractor.extract_listings():
            count = self.loader.load_listings_df(batch, self.config.data.listings_file)
            listings_count += count
        logger.info(f"Total listings loaded: {listings_count}")

        # Load calendar
        calendar_count = 0
        for cal_batch in self.extractor.extract_calendar():
            count = self.loader.load_calendar_df(
                cal_batch, self.config.data.calendar_file
            )
            calendar_count += count
        logger.info(f"Total calendar records loaded: {calendar_count}")

    def transform_data(self) -> None:
        """Run all transformations."""
        logger.info("Starting data transformations...")
        self.loader.run_all_transforms()
        logger.info("Transformations completed")

    def run_full_pipeline(self) -> None:
        """Run the complete ETL pipeline."""
        logger.info("=" * 50)
        logger.info("Starting Airbnb Occupancy ETL Pipeline")
        logger.info("=" * 50)

        try:
            self.setup_database()
            self.load_raw_data()
            self.transform_data()

            logger.info("=" * 50)
            logger.info("Pipeline completed successfully!")
            logger.info("=" * 50)

        except Exception as e:
            logger.error(f"Pipeline failed: {e}")
            raise
        finally:
            self.loader.disconnect()

    def run_incremental(self) -> None:
        """Run incremental update (load new data + transform)."""
        logger.info("Running incremental update...")
        self.load_raw_data()
        self.transform_data()
        logger.info("Incremental update completed")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Airbnb Occupancy ETL Pipeline")
    parser.add_argument(
        "--config",
        "-c",
        type=str,
        default=None,
        help="Path to config YAML file (default: configs/config.yaml)",
    )
    parser.add_argument(
        "--incremental", "-i", action="store_true", help="Run incremental update only"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run the pipeline and return a process exit code."""
    args = parse_args(argv)
    config_file = Path(args.config) if args.config else None

    pipeline = ETLPipeline(config_file)

    try:
        if args.incremental:
            pipeline.run_incremental()
        else:
            pipeline.run_full_pipeline()
        return 0
    except Exception as e:  # noqa: BLE001 - CLI boundary: report and exit non-zero
        logger.error(f"Pipeline failed: {e}")
        return 1
    finally:
        pipeline.loader.disconnect()


if __name__ == "__main__":
    sys.exit(main())
