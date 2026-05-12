"""NEXUS Dashboard server — serves React build + proxies /api/* to NEXUS API."""
from __future__ import annotations

import httpx
import os
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

API_BASE = os.getenv("NEXUS_API_URL", "http://localhost:8000")
PORT = int(os.getenv("DASHBOARD_PORT", "9000"))

_dist = Path(__file__).parent / "frontend" / "dist"

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


@app.get("/healthz")
async def healthz() -> JSONResponse:
    """Status do dashboard server: mostra se o bundle existe e quando foi gerado."""
    index = _dist / "index.html"
    built = index.exists()
    mtime = index.stat().st_mtime if built else None
    import datetime
    return JSONResponse({
        "status": "ok",
        "dist_exists": built,
        "dist_path": str(_dist),
        "index_mtime": datetime.datetime.fromtimestamp(mtime).isoformat() if mtime else None,
        "api_base": API_BASE,
    })


# Servir index.html com Cache-Control: no-cache (garante que o browser
# busca sempre a versão mais recente após um rebuild).
@app.get("/", include_in_schema=False)
@app.get("/{full_path:path}", include_in_schema=False)
async def spa(full_path: str = "", request: Request = None) -> Response:  # type: ignore[assignment]
    """Serve o SPA React: assets estáticos com cache, index.html sem cache."""
    # Assets compilados (js, css, icons) — têm hash no nome, podem ter cache longa
    if full_path.startswith("assets/"):
        asset = _dist / full_path
        if asset.is_file():
            return FileResponse(str(asset), headers={"Cache-Control": "public, max-age=31536000, immutable"})

    # Ficheiros estáticos na raiz (manifest.json, icons, etc.)
    if full_path and full_path != "index.html":
        static = _dist / full_path
        if static.is_file():
            return FileResponse(str(static))

    # index.html — sempre sem cache para que o browser carregue o bundle novo
    index = _dist / "index.html"
    if index.is_file():
        return FileResponse(
            str(index),
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )

    # dist/ não existe ou não foi construído
    return JSONResponse(
        {
            "error": "frontend_not_built",
            "detail": "Run: cd nexus/dashboard/frontend && npm ci && npm run build",
            "dist_checked": str(_dist),
        },
        status_code=503,
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("nexus.dashboard.server:app", host="0.0.0.0", port=PORT, reload=False)
