"""Tests for scrumbleeggs.config module."""
import pytest

from scrumbleeggs.config import Config, _parse_page_size, get_config


class TestParsePageSize:
    """Tests for the _parse_page_size helper."""

    def test_valid_integer_returns_int(self):
        assert _parse_page_size("20") == 20

    def test_minimum_value_one_is_valid(self):
        assert _parse_page_size("1") == 1

    def test_large_value_is_valid(self):
        assert _parse_page_size("10000") == 10000

    def test_zero_raises_value_error(self):
        with pytest.raises(ValueError, match="must be >= 1"):
            _parse_page_size("0")

    def test_negative_raises_value_error(self):
        with pytest.raises(ValueError, match="must be >= 1"):
            _parse_page_size("-5")

    def test_non_integer_string_raises_value_error(self):
        with pytest.raises(ValueError, match="must be an integer"):
            _parse_page_size("abc")

    def test_float_string_raises_value_error(self):
        with pytest.raises(ValueError, match="must be an integer"):
            _parse_page_size("3.14")

    def test_empty_string_raises_value_error(self):
        with pytest.raises(ValueError, match="must be an integer"):
            _parse_page_size("")


class TestConfig:
    """Tests for the Config dataclass defaults and env overrides."""

    def test_default_db_url_uses_home_dir(self):
        config = Config()
        assert "scrumbleeggs.db" in config.db_url
        assert config.db_url.startswith("sqlite:///")

    def test_default_log_level_is_warning(self):
        config = Config()
        assert config.log_level == "WARNING"

    def test_default_assignee_is_empty(self):
        config = Config()
        assert config.default_assignee == ""

    def test_default_page_size_is_20(self):
        config = Config()
        assert config.page_size == 20

    def test_default_prefix_is_sbe(self):
        config = Config()
        assert config.project_prefix == "SBE"

    def test_env_override_db_url(self, monkeypatch):
        monkeypatch.setenv("SBE_DB_URL", "sqlite:///custom.db")
        config = Config()
        assert config.db_url == "sqlite:///custom.db"

    def test_env_override_log_level(self, monkeypatch):
        monkeypatch.setenv("SBE_LOG_LEVEL", "DEBUG")
        config = Config()
        assert config.log_level == "DEBUG"

    def test_env_override_default_assignee(self, monkeypatch):
        monkeypatch.setenv("SBE_DEFAULT_ASSIGNEE", "bob")
        config = Config()
        assert config.default_assignee == "bob"

    def test_env_override_page_size(self, monkeypatch):
        monkeypatch.setenv("SBE_PAGE_SIZE", "50")
        config = Config()
        assert config.page_size == 50

    def test_env_override_project_prefix(self, monkeypatch):
        monkeypatch.setenv("SBE_PROJECT_PREFIX", "PROJ")
        config = Config()
        assert config.project_prefix == "PROJ"

    def test_invalid_page_size_env_raises(self, monkeypatch):
        monkeypatch.setenv("SBE_PAGE_SIZE", "notanumber")
        with pytest.raises(ValueError, match="must be an integer"):
            Config()


class TestGetConfig:
    """Tests for the get_config() factory function."""

    def test_returns_config_instance(self):
        result = get_config()
        assert isinstance(result, Config)

    def test_config_has_correct_defaults(self):
        config = get_config()
        assert config.page_size == 20
        assert config.project_prefix == "SBE"
