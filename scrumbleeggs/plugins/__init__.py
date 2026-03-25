"""Plugin loader — auto-discovers and registers plugins from this package.

Each plugin is a sub-package with:
  manifest.json   — id, name, version, nav config
  __init__.py     — exports router + configure(db) + models list
  template.html   — Alpine.js UI fragment rendered inside the main SPA

Plugins are mounted at:
  API:  /api/plugins/<plugin_id>/...
  View: view === 'plugin_<plugin_id>' (Alpine x-show)
"""
import importlib
import json
import logging
from pathlib import Path

from fastapi import FastAPI

logger = logging.getLogger(__name__)

_PLUGIN_DIR = Path(__file__).parent


def load_plugins(app: FastAPI, db) -> list[dict]:
    """Discover all plugin sub-packages, register their routes, create their
    tables, and return a list of plugin descriptors for the Jinja2 template.

    Args:
        app: The FastAPI application instance.
        db:  The Database facade (scrumbleeggs.db.Database).

    Returns:
        List of dicts with keys: id, name, version, description, nav, template.
    """
    plugins: list[dict] = []

    for plugin_dir in sorted(_PLUGIN_DIR.iterdir()):
        if not plugin_dir.is_dir() or plugin_dir.name.startswith("_"):
            continue
        manifest_path = plugin_dir / "manifest.json"
        if not manifest_path.exists():
            continue

        try:
            manifest = json.loads(manifest_path.read_text())
            plugin_id = manifest["id"]

            # Import the plugin package
            module = importlib.import_module(
                f".{plugin_dir.name}", package=__package__
            )

            # Hand the Database instance to the plugin
            if hasattr(module, "configure"):
                module.configure(db)

            # Create plugin DB tables
            if hasattr(module, "models"):
                from ..db import Base
                for model_cls in module.models:
                    model_cls.__table__.create(db.engine, checkfirst=True)

            # Mount FastAPI router
            if hasattr(module, "router"):
                app.include_router(
                    module.router,
                    prefix=f"/api/plugins/{plugin_id}",
                )

            # Load the UI template fragment
            template_path = plugin_dir / "template.html"
            template_html = (
                template_path.read_text() if template_path.exists() else ""
            )

            plugins.append({**manifest, "template": template_html})
            logger.info("Loaded plugin: %s v%s", manifest["name"], manifest.get("version", "?"))

        except Exception:
            logger.exception("Failed to load plugin from %s", plugin_dir.name)

    return plugins
