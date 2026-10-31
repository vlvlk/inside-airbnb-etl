"""Tests for the unified configuration layer (``src.config``)."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from src.config import (
    AppConfig,
    ConfigError,
    DatabaseSettings,
    DataSettings,
    LoggingSettings,
    PipelineSettings,
    get_config,
    reset_config,
    resolve_config_path,
)

ENV_ALIASES = (
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "DATA_PATH",
    "BATCH_SIZE",
    "CHUNK_SIZE",
    "VALIDATE_DATA",
    "SKIP_INVALID_ROWS",
    "USE_COPY",
    "LOG_LEVEL",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Isolate every test from the ambient environment and the config cache."""
    for name in ENV_ALIASES:
        monkeypatch.delenv(name, raising=False)
    reset_config()
    yield
    reset_config()


@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    """A minimal, valid declarative config file."""
    path = tmp_path / "config.yaml"
    path.write_text(
        """
database:
  host: yaml-host
  port: 1111
  name: yaml-db
data:
  data_path: ./yaml-data
pipeline:
  batch_size: 777
logging:
  level: WARNING
""",
        encoding="utf-8",
    )
    return path


class TestYamlLoading:
    """Values are read from the declarative YAML file."""

    def test_reads_all_sections(self, config_file: Path):
        config = AppConfig(config_file)

        assert config.database.host == "yaml-host"
        assert config.database.port == 1111
        assert config.database.name == "yaml-db"
        assert config.data.data_path == Path("./yaml-data")
        assert config.pipeline.batch_size == 777
        assert config.logging.level == "WARNING"

    def test_yaml_port_keeps_int_type(self, config_file: Path):
        """A YAML port must be an int, not a string (old setattr bug)."""
        assert isinstance(AppConfig(config_file).database.port, int)

    def test_derived_paths_follow_data_path(self, config_file: Path):
        data = AppConfig(config_file).data

        assert data.raw_path == Path("./yaml-data/raw")
        assert data.processed_path == Path("./yaml-data/processed")
        assert data.listings_path == Path("./yaml-data/raw/listings.csv")

    def test_missing_section_falls_back_to_defaults(self, tmp_path: Path):
        path = tmp_path / "partial.yaml"
        path.write_text("database:\n  host: only-host\n", encoding="utf-8")

        config = AppConfig(path)

        assert config.database.host == "only-host"
        assert config.pipeline.batch_size == 100000
        assert config.logging.level == "INFO"

    def test_missing_file_falls_back_to_defaults(self, tmp_path: Path):
        config = AppConfig(tmp_path / "does-not-exist.yaml")

        assert config.database.host == "localhost"
        assert config.data.data_path == Path("./data")


class TestPrecedence:
    """CLI > env > .env > YAML > defaults."""

    def test_env_overrides_yaml(self, config_file: Path, monkeypatch):
        monkeypatch.setenv("POSTGRES_HOST", "env-host")
        monkeypatch.setenv("BATCH_SIZE", "12345")

        config = AppConfig(config_file)

        assert config.database.host == "env-host"
        assert config.pipeline.batch_size == 12345

    def test_cli_overrides_env_and_yaml(self, config_file: Path, monkeypatch):
        monkeypatch.setenv("POSTGRES_HOST", "env-host")

        config = AppConfig(config_file, database={"host": "cli-host"})

        assert config.database.host == "cli-host"

    def test_yaml_overrides_defaults(self, config_file: Path):
        assert AppConfig(config_file).database.host == "yaml-host"

    def test_defaults_used_without_yaml(self, tmp_path: Path):
        config = AppConfig(tmp_path / "missing.yaml")

        assert config.database.host == "localhost"
        assert config.pipeline.batch_size == 100000


class TestStrictness:
    """Malformed configuration fails loudly instead of silently."""

    def test_unknown_key_in_yaml_raises(self, tmp_path: Path):
        path = tmp_path / "typo.yaml"
        path.write_text("pipeline:\n  batchsize: 5\n", encoding="utf-8")

        with pytest.raises(ConfigError, match="batchsize"):
            AppConfig(path)

    def test_unknown_key_message_lists_valid_keys(self, tmp_path: Path):
        path = tmp_path / "typo.yaml"
        path.write_text("database:\n  hots: x\n", encoding="utf-8")

        with pytest.raises(ConfigError, match="hots"):
            AppConfig(path)

    def test_non_mapping_section_raises(self, tmp_path: Path):
        path = tmp_path / "bad.yaml"
        path.write_text("pipeline: 42\n", encoding="utf-8")

        with pytest.raises(ConfigError, match="must be a mapping"):
            AppConfig(path)

    def test_non_mapping_document_raises(self, tmp_path: Path):
        path = tmp_path / "bad.yaml"
        path.write_text("- just\n- a\n- list\n", encoding="utf-8")

        with pytest.raises(ConfigError, match="mapping"):
            AppConfig(path)

    def test_invalid_type_raises(self, tmp_path: Path):
        path = tmp_path / "bad.yaml"
        path.write_text("pipeline:\n  batch_size: not-a-number\n", encoding="utf-8")

        with pytest.raises(ValidationError):
            AppConfig(path)


class TestImmutability:
    """The built configuration cannot be mutated."""

    def test_section_is_frozen(self, config_file: Path):
        config = AppConfig(config_file)

        with pytest.raises(ValidationError):
            config.database.host = "mutated"  # type: ignore[misc]

    def test_aggregate_is_frozen(self, config_file: Path):
        config = AppConfig(config_file)

        with pytest.raises(ValidationError):
            config.database = DatabaseSettings()  # type: ignore[misc]


class TestResolveConfigPath:
    """Default path discovery."""

    def test_explicit_path_is_returned_as_is(self, tmp_path: Path):
        path = tmp_path / "custom.yaml"

        assert resolve_config_path(path) == path
        assert resolve_config_path(str(path)) == path

    def test_default_path_used_when_it_exists(self, monkeypatch, tmp_path: Path):
        default = tmp_path / "configs" / "config.yaml"
        default.parent.mkdir()
        default.write_text("logging:\n  level: INFO\n", encoding="utf-8")
        monkeypatch.setattr("src.config.DEFAULT_CONFIG_PATH", default)

        assert resolve_config_path() == default

    def test_returns_none_when_default_is_absent(self, monkeypatch, tmp_path: Path):
        monkeypatch.setattr("src.config.DEFAULT_CONFIG_PATH", tmp_path / "absent.yaml")

        assert resolve_config_path() is None


class TestGetConfigCache:
    """Caching is keyed by resolved path, not by first call."""

    def test_same_path_returns_same_instance(self, config_file: Path):
        assert get_config(config_file) is get_config(config_file)

    def test_different_paths_do_not_share_state(self, tmp_path: Path):
        first = tmp_path / "a.yaml"
        first.write_text("database:\n  host: host-a\n", encoding="utf-8")
        second = tmp_path / "b.yaml"
        second.write_text("database:\n  host: host-b\n", encoding="utf-8")

        assert get_config(first).database.host == "host-a"
        assert get_config(second).database.host == "host-b"
        assert get_config(first).database.host == "host-a"

    def test_reset_clears_cache(self, config_file: Path):
        before = get_config(config_file)
        reset_config()

        assert get_config(config_file) is not before


class TestSectionsAreIndependent:
    """Each section is a standalone, typed settings object."""

    def test_generic_system_env_vars_do_not_leak(self, monkeypatch):
        """``USER``/``NAME``/``HOST``/``PORT`` must not override settings.

        Sections read env vars strictly by alias, so common system variables
        cannot silently win over ``database.user``, ``database.name``, etc.
        """
        monkeypatch.setenv("USER", "shell-user")
        monkeypatch.setenv("NAME", "shell-name")
        monkeypatch.setenv("HOST", "shell-host")
        monkeypatch.setenv("PORT", "9999")

        config = AppConfig()

        assert config.database.user == "airbnb"
        assert config.database.name == "airbnb"
        assert config.database.host == "localhost"
        assert config.database.port == 5432

    def test_database_url_uses_env(self, monkeypatch):
        monkeypatch.setenv("POSTGRES_HOST", "db.internal")
        monkeypatch.setenv("POSTGRES_PORT", "6000")
        monkeypatch.setenv("POSTGRES_USER", "u")
        monkeypatch.setenv("POSTGRES_PASSWORD", "p")
        monkeypatch.setenv("POSTGRES_DB", "d")

        db = DatabaseSettings()

        assert db.url == "postgresql+psycopg2://u:p@db.internal:6000/d"

    def test_data_paths_are_derived(self):
        data = DataSettings(data_path=Path("/srv/airbnb"))

        assert data.raw_path == Path("/srv/airbnb/raw")
        assert data.calendar_path == Path("/srv/airbnb/raw/calendar.csv")

    def test_pipeline_defaults(self):
        pipeline = PipelineSettings()

        assert pipeline.batch_size == 100000
        assert pipeline.chunk_size == 250000
        assert pipeline.validate_data is True
        assert pipeline.skip_invalid_rows is False
        assert pipeline.use_copy is True

    def test_logging_defaults(self):
        logging_settings = LoggingSettings()

        assert logging_settings.level == "INFO"
        assert "%(levelname)s" in logging_settings.format
