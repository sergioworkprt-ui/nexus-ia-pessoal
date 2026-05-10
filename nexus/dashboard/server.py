"""NEXUS Dashboard server — serves React build + proxies /api/* to NEXUS API."""
from __future__ import annotations

import httpx
import os
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

API_BASE = os.getenv("NEXUS_API_URL", "http://localhost:8000")
PORT = int(os.getenv("DASHBOARD_PORT", "9000"))

app = FastAPI(title="NEXUS Dashboard", docs_url=None, redoc_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_client = httpx.AsyncClient(base_url=API_BASE, timeout=60.0)


@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def proxy(path: str, request: Request) -> Response:
    """Transparent reverse proxy to NEXUS API."""
    body = await request.body()
    headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in ("host", "content-length")
    }
    try:
        resp = await _client.request(
            method=request.method,
            url=f"/{path}",
            content=body,
            headers=headers,
            params=dict(request.query_params),
        )
        return Response(
            content=resp.content,
            status_code=resp.status_code,
            headers=dict(resp.headers),
        )
    except httpx.ConnectError:
        return JSONResponse({"error": "api_unavailable", "detail": "NEXUS API not reachable"}, status_code=503)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": "proxy_error", "detail": str(exc)}, status_code=502)


# Serve React static build — must be registered AFTER /api proxy
_dist = Path(__file__).parent / "frontend" / "dist"
if _dist.is_dir():
    app.mount("/", StaticFiles(directory=str(_dist), html=True), name="static")
else:
    @app.get("/")
    async def not_built() -> JSONResponse:
        return JSONResponse(
            {"error": "frontend_not_built", "detail": "Run: npm ci && npm run build inside nexus/dashboard/frontend/"},
            status_code=503,
        )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("nexus.dashboard.server:app", host="0.0.0.0", port=PORT, reload=False)
