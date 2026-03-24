"""Standalone Performance Dashboard Server.

Runs on a separate port to avoid impacting the main application.
Proxies metrics requests to the main server.

Usage:
    python -m scrumbleeggs.web.perf_server --port 8001 --target http://localhost:8000

This server:
- Serves the performance dashboard UI
- Proxies /api/perf/timeseries to the main server
- Does NOT affect main server's metrics (requests are filtered)
"""
import argparse
import logging
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
import uvicorn

logger = logging.getLogger(__name__)

_here = Path(__file__).parent
templates = Jinja2Templates(directory=str(_here / "templates"))

app = FastAPI(title="Scrumbleeggs Performance Monitor", version="0.1.0")

# Target server URL - set via startup
_target_url: str = "http://localhost:8000"


@app.get("/", response_class=HTMLResponse)
async def perf_page(request: Request):
    """Redirect to /perf for convenience."""
    return templates.TemplateResponse("perf_standalone.html", {"request": request})


@app.get("/perf", response_class=HTMLResponse)
async def perf_dashboard(request: Request):
    """Serve the performance dashboard."""
    return templates.TemplateResponse("perf_standalone.html", {"request": request})


@app.get("/api/perf/timeseries")
async def proxy_timeseries():
    """Proxy timeseries request to the main server."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{_target_url}/api/perf/timeseries")
            return JSONResponse(content=resp.json(), status_code=resp.status_code)
    except httpx.RequestError as e:
        logger.error(f"Failed to fetch from target: {e}")
        return JSONResponse(
            content={"error": f"Cannot reach target server at {_target_url}"},
            status_code=503,
        )


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok", "target": _target_url}


def main():
    parser = argparse.ArgumentParser(description="Standalone Performance Dashboard")
    parser.add_argument(
        "--port", type=int, default=8001, help="Port to run the perf server on"
    )
    parser.add_argument(
        "--target",
        type=str,
        default="http://localhost:8000",
        help="URL of the main server to monitor",
    )
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host to bind to")
    args = parser.parse_args()

    global _target_url
    _target_url = args.target

    print(f"\n🔍 Scrumbleeggs Performance Monitor")
    print(f"   Dashboard: http://localhost:{args.port}/perf")
    print(f"   Monitoring: {args.target}")
    print()

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
