"""Tests for CSV extraction module."""

from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd
import pytest

from src.config import (
    AppConfig,
    DatabaseSettings,
    DataSettings,
    LoggingSettings,
    PipelineSettings,
)
from src.extract.csv_extractor import (
    CSVExtractor,
    extract_calendar_df,
    extract_listings_df,
)


@pytest.fixture
def mock_config():
    """Create a mock configuration."""
    config = Mock(spec=AppConfig)
    config.database = Mock(spec=DatabaseSettings)
    config.data = Mock(spec=DataSettings)
    # Path-like mocks whose .exists() returns True so the extractor proceeds
    # to the (mocked) pandas.read_csv instead of failing the pre-flight check.
    config.data.listings_path = Mock(spec=Path)
    config.data.listings_path.exists.return_value = True
    config.data.calendar_path = Mock(spec=Path)
    config.data.calendar_path.exists.return_value = True
    config.data.listings_file = "listings.csv"
    config.data.calendar_file = "calendar.csv"
    config.pipeline = Mock(spec=PipelineSettings)
    config.pipeline.batch_size = 1000
    config.pipeline.chunk_size = 1000
    config.pipeline.validate_data = True
    config.pipeline.skip_invalid_rows = False
    config.logging = Mock(spec=LoggingSettings)
    return config


@pytest.fixture
def sample_listings_df():
    """Create sample listings DataFrame."""
    return pd.DataFrame(
        {
            "id": ["1", "2", "3"],
            "name": ["Listing 1", "Listing 2", "Listing 3"],
            "host_id": ["100", "200", "300"],
            "neighbourhood_cleansed": ["Downtown", "Uptown", "Midtown"],
            "price": ["$100.00", "$200.00", "$150.00"],
            "room_type": ["Entire home/apt", "Private room", "Entire home/apt"],
        }
    )


@pytest.fixture
def sample_calendar_df():
    """Create sample calendar DataFrame."""
    return pd.DataFrame(
        {
            "listing_id": ["1", "1", "2", "2"],
            "date": ["2024-01-01", "2024-01-02", "2024-01-01", "2024-01-02"],
            "available": ["t", "f", "t", "t"],
            "minimum_nights": ["1", "1", "2", "2"],
            "maximum_nights": ["30", "30", "30", "30"],
        }
    )


class TestCSVExtractor:
    """Tests for CSVExtractor class."""

    def test_init(self, mock_config):
        """Test extractor initialization."""
        with patch("src.extract.csv_extractor.get_config", return_value=mock_config):
            extractor = CSVExtractor()
            assert extractor.batch_size == 1000
            assert extractor.chunk_size == 1000
            assert extractor.validate is True
            assert extractor.skip_invalid is False

    def test_extract_listings_success(self, mock_config, sample_listings_df):
        """Test successful listings extraction returns normalized DataFrames."""
        with (
            patch("src.extract.csv_extractor.get_config", return_value=mock_config),
            patch("pandas.read_csv") as mock_read_csv,
        ):
            mock_read_csv.return_value = iter([sample_listings_df])

            extractor = CSVExtractor()
            batches = list(extractor.extract_listings())

            assert len(batches) == 1
            assert isinstance(batches[0], pd.DataFrame)
            assert len(batches[0]) == 3
            assert list(batches[0]["id"]) == ["1", "2", "3"]
            assert list(batches[0]["name"]) == ["Listing 1", "Listing 2", "Listing 3"]
            # Price stays verbatim text in the raw layer (cleaned in staging).
            assert batches[0]["price"].iloc[0] == "$100.00"

    def test_extract_calendar_success(self, mock_config, sample_calendar_df):
        """Test successful calendar extraction returns normalized DataFrames."""
        with (
            patch("src.extract.csv_extractor.get_config", return_value=mock_config),
            patch("pandas.read_csv") as mock_read_csv,
        ):
            mock_read_csv.return_value = iter([sample_calendar_df])

            extractor = CSVExtractor()
            batches = list(extractor.extract_calendar())

            assert len(batches) == 1
            assert isinstance(batches[0], pd.DataFrame)
            assert len(batches[0]) == 4
            assert list(batches[0]["listing_id"]) == ["1", "1", "2", "2"]
            assert list(batches[0]["available"]) == ["t", "f", "t", "t"]
            assert batches[0]["date"].iloc[0] == "2024-01-01"

    def test_extract_splits_into_batches(self, mock_config, sample_listings_df):
        """A chunk larger than batch_size is yielded in batch_size slices."""
        mock_config.pipeline.batch_size = 2
        mock_config.pipeline.chunk_size = 1000

        with (
            patch("src.extract.csv_extractor.get_config", return_value=mock_config),
            patch("pandas.read_csv", return_value=iter([sample_listings_df])),
        ):
            extractor = CSVExtractor()
            batches = list(extractor.extract_listings())

            assert [len(b) for b in batches] == [2, 1]

    def test_extract_listings_file_not_found(self, mock_config):
        """Test extraction with missing file."""
        with (
            patch("src.extract.csv_extractor.get_config", return_value=mock_config),
            patch("pandas.read_csv", side_effect=FileNotFoundError("Not found")),
        ):
            extractor = CSVExtractor()
            with pytest.raises(FileNotFoundError):
                list(extractor.extract_listings())

    def test_extract_with_validation_error_skip(self, mock_config):
        """Test extraction with validation errors and skip_invalid=True."""
        mock_config.pipeline.skip_invalid_rows = True
        mock_config.pipeline.validate_data = True

        bad_df = pd.DataFrame(
            {
                "id": ["1", "invalid", "3"],
                "name": ["Good", "Bad", "Good"],
            }
        )

        with (
            patch("src.extract.csv_extractor.get_config", return_value=mock_config),
            patch("pandas.read_csv", return_value=iter([bad_df])),
        ):
            extractor = CSVExtractor()
            batches = list(extractor.extract_listings())

            # Should skip invalid row
            assert len(batches) == 1
            assert len(batches[0]) == 2
            assert list(batches[0]["id"]) == ["1", "3"]

    def test_extract_with_validation_error_raise(self, mock_config):
        """Test extraction with validation errors and skip_invalid=False."""
        mock_config.pipeline.skip_invalid_rows = False
        mock_config.pipeline.validate_data = True

        bad_df = pd.DataFrame(
            {
                "id": ["1", "invalid"],
            }
        )

        with (
            patch("src.extract.csv_extractor.get_config", return_value=mock_config),
            patch("pandas.read_csv", return_value=iter([bad_df])),
        ):
            extractor = CSVExtractor()
            with pytest.raises(ValueError):
                list(extractor.extract_listings())

    def test_extract_without_validation(self, mock_config, sample_listings_df):
        """Test extraction without validation still normalizes the frame."""
        mock_config.pipeline.validate_data = False

        with (
            patch("src.extract.csv_extractor.get_config", return_value=mock_config),
            patch("pandas.read_csv", return_value=iter([sample_listings_df])),
        ):
            extractor = CSVExtractor()
            batches = list(extractor.extract_listings())

            assert len(batches) == 1
            assert len(batches[0]) == 3
            assert list(batches[0]["id"]) == ["1", "2", "3"]


class TestConvenienceFunctions:
    """Tests for convenience functions."""

    def test_extract_listings_df(self, mock_config, sample_listings_df):
        """Test extract_listings_df function."""
        with (
            patch("src.extract.csv_extractor.get_config", return_value=mock_config),
            patch("pandas.read_csv", return_value=sample_listings_df) as mock_read,
        ):
            df = extract_listings_df()
            assert len(df) == 3
            mock_read.assert_called_once()

    def test_extract_listings_df_custom_path(self, mock_config, sample_listings_df):
        """Test extract_listings_df with custom path."""
        custom_path = Path("/custom/path/listings.csv")
        with (
            patch("src.extract.csv_extractor.get_config", return_value=mock_config),
            patch("pandas.read_csv", return_value=sample_listings_df) as mock_read,
        ):
            df = extract_listings_df(custom_path)
            assert len(df) == 3
            mock_read.assert_called_once_with(
                custom_path, dtype=str, keep_default_na=False
            )

    def test_extract_calendar_df(self, mock_config, sample_calendar_df):
        """Test extract_calendar_df function."""
        with (
            patch("src.extract.csv_extractor.get_config", return_value=mock_config),
            patch("pandas.read_csv", return_value=sample_calendar_df) as mock_read,
        ):
            df = extract_calendar_df()
            assert len(df) == 4
            mock_read.assert_called_once()
