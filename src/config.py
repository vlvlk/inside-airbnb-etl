"""Configuration management for Inside Airbnb ETL.

Single source of truth
----------------------
All settings live in one typed :class:`AppConfig` object built from
``pydantic-settings``. Values are resolved through an explicit, documented
precedence chain (highest priority first):

1. explicit init/CLI arguments,
2. process environment variables,
3. ``.env`` file,
4. ``configs/config.yaml`` (the primary declarative file),
5. defaults declared in the code.

``configs/config.yaml`` is the file people edit by hand; environment variables
exist to override it (CI, Docker, one-off runs) without touching the file.
Unknown keys are rejected with a clear error instead of being silently ignored.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, ClassVar

import yaml
from pydantic import Field
from pydantic.fields import FieldInfo
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

#: Default declarative config file, used when no explicit path is given.
DEFAULT_CONFIG_PATH = Path("configs/config.yaml")

#: Default ``.env`` file, used by every settings section.
DEFAULT_ENV_FILE = Path(".env")

LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

logger = logging.getLogger(__name__)


class ConfigError(RuntimeError):
    """Raised when the configuration is malformed or inconsistent."""


class YamlSectionSource(PydanticBaseSettingsSource):
    """Settings source reading one top-level section of a YAML file.

    Sits *below* environment variables in the precedence chain, so a YAML value
    is used only when neither init arguments, the process environment, nor the
    ``.env`` file provide one.

    A missing file or a missing section is not an error: the section simply
    contributes nothing and the defaults apply. An unknown key inside an
    existing section *is* an error, so typos surface immediately.
    """

    def __init__(
        self,
        settings_cls: type[BaseSettings],
        yaml_file: Path | str,
        section: str,
    ) -> None:
        super().__init__(settings_cls)
        self.yaml_file = Path(yaml_file)
        self.section = section
        self._data = self._load_section()

    def _load_section(self) -> dict[str, Any]:
        if not self.yaml_file.exists():
            return {}

        raw = yaml.safe_load(self.yaml_file.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ConfigError(
                f"{self.yaml_file} must contain a mapping at the top level, "
                f"got {type(raw).__name__}"
            )

        section = raw.get(self.section)
        if section is None:
            return {}
        if not isinstance(section, dict):
            raise ConfigError(
                f"Section '{self.section}' in {self.yaml_file} must be a mapping, "
                f"got {type(section).__name__}"
            )
        return section

    def get_field_value(
        self, field: FieldInfo, field_name: str
    ) -> tuple[Any, str, bool]:
        return self._data.get(field_name), field_name, False

    def __call__(self) -> dict[str, Any]:
        known = set(self.settings_cls.model_fields)
        unknown = sorted(set(self._data) - known)
        if unknown:
            raise ConfigError(
                f"Unknown key(s) {unknown} in section '{self.section}' of "
                f"{self.yaml_file}. Valid keys: {sorted(known)}"
            )

        # YAML is written with field names; settings are validated by alias.
        return {
            alias if isinstance(alias := field.alias, str) else name: self._data[name]
            for name, field in self.settings_cls.model_fields.items()
            if name in self._data
        }


class SectionSettings(BaseSettings):
    """Base class for configuration sections.

    Every section reads its own environment variables (via ``alias``) and its
    own YAML section, and is immutable once built.

    ``populate_by_name`` is deliberately left off: environment variables are
    read *only* through the documented aliases. Otherwise generic system
    variables such as ``USER``, ``NAME``, ``HOST`` or ``PORT`` would silently
    override settings like ``database.user`` or ``database.name``.
    """

    #: Top-level key of this section inside ``config.yaml``.
    yaml_section: ClassVar[str] = ""

    model_config = SettingsConfigDict(
        env_file=DEFAULT_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # ``InitSettingsSource`` stores the raw init arguments; the private
        # ``_yaml_file`` marker is consumed here so it never reaches validation.
        init_kwargs: dict[str, Any] = getattr(init_settings, "init_kwargs", {})
        yaml_file = init_kwargs.pop("_yaml_file", None)

        sources: list[PydanticBaseSettingsSource] = [
            init_settings,
            env_settings,
            dotenv_settings,
        ]
        if yaml_file is not None:
            sources.append(YamlSectionSource(settings_cls, yaml_file, cls.yaml_section))
        sources.append(file_secret_settings)
        return tuple(sources)


class DatabaseSettings(SectionSettings):
    """PostgreSQL connection settings."""

    yaml_section: ClassVar[str] = "database"

    host: str = Field(default="localhost", alias="POSTGRES_HOST")
    port: int = Field(default=5432, alias="POSTGRES_PORT")
    name: str = Field(default="airbnb", alias="POSTGRES_DB")
    user: str = Field(default="airbnb", alias="POSTGRES_USER")
    password: str = Field(default="airbnb", alias="POSTGRES_PASSWORD")

    @property
    def url(self) -> str:
        """Return SQLAlchemy connection URL."""
        return (
            f"postgresql+psycopg2://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{self.name}"
        )


class DataSettings(SectionSettings):
    """Data paths configuration.

    ``data_path`` is the single root directory; the raw/processed sub-paths are
    derived from it, so they can never drift apart or collide on one alias.
    """

    yaml_section: ClassVar[str] = "data"

    data_path: Path = Field(default=Path("./data"), alias="DATA_PATH")
    # The bundled snapshot is Parquet (see docs/schema.md); these defaults must
    # match ``configs/config.yaml`` so a config-less run behaves identically.
    listings_file: str = "listings.parquet"
    calendar_file: str = "calendar.parquet"

    @property
    def raw_path(self) -> Path:
        """Directory holding the raw CSV inputs (``<DATA_PATH>/raw``)."""
        return self.data_path / "raw"

    @property
    def processed_path(self) -> Path:
        """Directory for processed outputs (``<DATA_PATH>/processed``)."""
        return self.data_path / "processed"

    @property
    def listings_path(self) -> Path:
        """Full path to the listings CSV."""
        return self.raw_path / self.listings_file

    @property
    def calendar_path(self) -> Path:
        """Full path to the calendar CSV."""
        return self.raw_path / self.calendar_file


class DashboardSettings(SectionSettings):
    """Dashboard data-source settings.

    The dashboard can read the ``marts`` schema from PostgreSQL (the production
    path, populated by the ETL pipeline) or from a local DuckDB file built
    straight out of the bundled Parquet snapshot. The DuckDB path exists so a
    fresh clone — and a public deployment — can serve the dashboard without a
    database server and without waiting for the 8M-row load.

    ``source: auto`` tries PostgreSQL first and falls back to DuckDB, so a
    reviewer who has not started Docker still gets a working dashboard.
    """

    yaml_section: ClassVar[str] = "dashboard"

    #: ``auto`` | ``postgres`` | ``duckdb``.
    source: str = Field(default="auto", alias="DASHBOARD_SOURCE")
    #: Directory holding the Parquet demo layer (one file per table).
    demo_dir: str = Field(default="data/demo", alias="DASHBOARD_DEMO_DIR")

    @property
    def demo_path(self) -> Path:
        """Path to the directory holding the Parquet demo layer."""
        return Path(self.demo_dir)


class PipelineSettings(SectionSettings):
    """ETL pipeline tuning parameters."""

    yaml_section: ClassVar[str] = "pipeline"

    batch_size: int = Field(default=100000, alias="BATCH_SIZE")
    chunk_size: int = Field(default=250000, alias="CHUNK_SIZE")
    validate_data: bool = Field(default=True, alias="VALIDATE_DATA")
    skip_invalid_rows: bool = Field(default=False, alias="SKIP_INVALID_ROWS")
    use_copy: bool = Field(default=True, alias="USE_COPY")
    # A full run is a *replace*, not a merge: the raw/staging/marts tables are
    # truncated before the load so rows that are absent from the new snapshot
    # (e.g. the previous city) cannot survive the upsert and leak into the
    # marts. Set false only for a deliberate incremental append.
    replace_on_load: bool = Field(default=True, alias="REPLACE_ON_LOAD")


class LoggingSettings(SectionSettings):
    """Logging configuration."""

    yaml_section: ClassVar[str] = "logging"

    level: str = Field(default="INFO", alias="LOG_LEVEL")
    format: str = LOG_FORMAT


class AppConfig(BaseSettings):
    """Typed, immutable aggregate of every configuration section.

    This is a pure aggregator: it has no sources of its own, so a value can only
    reach it through one of the sections, each of which applies the documented
    precedence chain. Section overrides can be passed as keyword arguments, e.g.
    ``AppConfig("configs/config.yaml", database={"host": "cli-host"})``.
    """

    model_config = SettingsConfigDict(extra="forbid", frozen=True)

    database: DatabaseSettings
    data: DataSettings
    dashboard: DashboardSettings
    pipeline: PipelineSettings
    logging: LoggingSettings

    def __init__(
        self,
        config_path: Path | str | None = None,
        **overrides: dict[str, Any],
    ) -> None:
        yaml_file = resolve_config_path(config_path)
        super().__init__(
            database=DatabaseSettings(
                _yaml_file=yaml_file,  # type: ignore[call-arg]
                **translate_overrides(DatabaseSettings, overrides.get("database", {})),
            ),
            data=DataSettings(
                _yaml_file=yaml_file,  # type: ignore[call-arg]
                **translate_overrides(DataSettings, overrides.get("data", {})),
            ),
            dashboard=DashboardSettings(
                _yaml_file=yaml_file,  # type: ignore[call-arg]
                **translate_overrides(
                    DashboardSettings, overrides.get("dashboard", {})
                ),
            ),
            pipeline=PipelineSettings(
                _yaml_file=yaml_file,  # type: ignore[call-arg]
                **translate_overrides(PipelineSettings, overrides.get("pipeline", {})),
            ),
            logging=LoggingSettings(
                _yaml_file=yaml_file,  # type: ignore[call-arg]
                **translate_overrides(LoggingSettings, overrides.get("logging", {})),
            ),
        )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # Sections own all sources; the aggregate only accepts built sections.
        return (init_settings,)


def translate_overrides(
    settings_cls: type[SectionSettings], overrides: dict[str, Any]
) -> dict[str, Any]:
    """Map override keys from field names to environment aliases.

    Sections read environment variables strictly by alias, so an init override
    given as ``{"host": "cli-host"}`` has to be translated to the alias
    (``POSTGRES_HOST``) before being passed on. Unknown keys raise, matching the
    strictness of the YAML source.
    """
    translated: dict[str, Any] = {}
    for key, value in overrides.items():
        field = settings_cls.model_fields.get(key)
        if field is None:
            raise ConfigError(
                f"Unknown override '{key}' for {settings_cls.__name__}. "
                f"Valid keys: {sorted(settings_cls.model_fields)}"
            )
        alias = field.alias
        translated[alias if isinstance(alias, str) else key] = value
    return translated


def resolve_config_path(config_path: Path | str | None = None) -> Path | None:
    """Return the YAML file to read, or ``None`` when there is nothing to read.

    When no explicit path is given, :data:`DEFAULT_CONFIG_PATH` is used if it
    exists, so the declarative file is honoured by default instead of only when
    ``--config`` is passed by hand.
    """
    if config_path is not None:
        return Path(config_path)
    return DEFAULT_CONFIG_PATH if DEFAULT_CONFIG_PATH.exists() else None


def setup_logging(config: AppConfig) -> None:
    """Apply :class:`LoggingSettings` to the root logger."""
    logging.basicConfig(level=config.logging.level, format=config.logging.format)


_config_cache: dict[Path | None, AppConfig] = {}


def get_config(config_path: Path | str | None = None) -> AppConfig:
    """Return the configuration for ``config_path``, building it once.

    The cache is keyed by resolved path, so different paths yield different
    configurations instead of the first one winning for the whole process.
    """
    key = resolve_config_path(config_path)
    if key not in _config_cache:
        _config_cache[key] = AppConfig(key)
    return _config_cache[key]


def reset_config() -> None:
    """Clear the configuration cache (used by tests)."""
    _config_cache.clear()
