"""Configuration module for scrumbleeggs — loads settings from env/dotenv."""
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_DEFAULT_DB = str(Path.home() / ".scrumbleeggs" / "scrumbleeggs.db")


def _parse_page_size(value: str) -> int:
    """Parse the SBE_PAGE_SIZE env var with a clear error on bad input."""
    try:
        size = int(value)
    except ValueError:
        raise ValueError(
            f"SBE_PAGE_SIZE must be an integer, got: {value!r}"
        ) from None
    if size < 1:
        raise ValueError(f"SBE_PAGE_SIZE must be >= 1, got: {size}")
    return size


@dataclass
class Config:
    """Application configuration loaded from environment variables.

    Attributes:
        db_url: SQLAlchemy database URL (swap-ready for any backend).
        log_level: Python logging level string.
        default_assignee: Pre-filled assignee name for new tickets.
        page_size: Default number of tickets per paginated list.
        project_prefix: Ticket key prefix (e.g. SBE -> SBE-1, SBE-2).
    """

    db_url: str = field(
        default_factory=lambda: os.getenv("SBE_DB_URL", f"sqlite:///{_DEFAULT_DB}")
    )
    log_level: str = field(default_factory=lambda: os.getenv("SBE_LOG_LEVEL", "WARNING"))
    default_assignee: str = field(default_factory=lambda: os.getenv("SBE_DEFAULT_ASSIGNEE", ""))
    page_size: int = field(
        default_factory=lambda: _parse_page_size(os.getenv("SBE_PAGE_SIZE", "20"))
    )
    project_prefix: str = field(
        default_factory=lambda: os.getenv("SBE_PROJECT_PREFIX", "SBE")
    )


def get_config() -> Config:
    """Return a Config instance populated from the current environment.

    Returns:
        Config: Fully populated configuration object.
    """
    config = Config()
    logging.basicConfig(level=getattr(logging, config.log_level, logging.WARNING))
    return config
