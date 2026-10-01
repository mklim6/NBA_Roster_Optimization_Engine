from __future__ import annotations

from datetime import datetime, timezone

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

SERVICE_NAME = "nba-franchise-v3-bridge"
API_VERSION = "0.1.0"


async def health(_: Request) -> JSONResponse:
    """Return a tiny liveness payload for the Godot desktop client."""
    return JSONResponse(
        {
            "status": "ok",
            "service": SERVICE_NAME,
            "api_version": API_VERSION,
            "phase": "V3 Phase 1",
            "read_only": True,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        }
    )


async def project_meta(_: Request) -> JSONResponse:
    """Describe the desktop shell without touching franchise save state."""
    return JSONResponse(
        {
            "project": "NBA Franchise Simulator",
            "release_line": "V3 desktop development",
            "backend": "Python",
            "client": "Godot",
            "simulation_source": "validated V2 engine",
            "save_access": "disabled_in_phase_1",
            "api_version": API_VERSION,
        }
    )


async def not_found(_: Request, __: Exception) -> JSONResponse:
    return JSONResponse({"error": "not_found"}, status_code=404)


routes = [
    Route("/health", health, methods=["GET"]),
    Route("/v3/meta", project_meta, methods=["GET"]),
]

app = Starlette(
    debug=False,
    routes=routes,
    exception_handlers={404: not_found},
)
