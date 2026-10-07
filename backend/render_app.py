"""Single-service packaging only; the analysis API is unchanged."""
import os
from pathlib import Path

from starlette.applications import Starlette
from starlette.responses import FileResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from backend.main import app as api


def create_app(static_dir: str | Path | None = None):
    root = Path(static_dir or os.getenv('FRONTEND_DIST', '/app/frontend/dist'))
    if not (root / 'index.html').is_file():
        raise RuntimeError('Built frontend is missing')

    async def index(request):
        return FileResponse(root / 'index.html', headers={
            'Cache-Control': 'no-store',
            'X-Content-Type-Options': 'nosniff',
            'Referrer-Policy': 'no-referrer',
        })

    # Only built assets are public. Unknown API/docs paths remain API 404s;
    # runtime data, configuration and source directories are never mounted.
    return Starlette(routes=[
        Route('/', index),
        Mount('/assets', StaticFiles(directory=root / 'assets')),
        Mount('/', app=api),
    ])
