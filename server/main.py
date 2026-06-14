import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import db
from .admin import router as admin_router
from .models import FlagRequest

WEBAPP_DIR = Path(__file__).parent.parent / "webapp"
_API_KEYS_FILE = Path(__file__).parent.parent / "config" / "api_keys.txt"

# Rate limiting: 60 requests/min per IP; API key holders are exempt
RATE_LIMIT = 60
RATE_WINDOW = 60.0
_rate_store: dict[str, tuple[int, float]] = {}
_rate_lock = threading.Lock()
_api_keys: set[str] = set()


def _load_api_keys() -> set[str]:
    _API_KEYS_FILE.parent.mkdir(exist_ok=True)
    if not _API_KEYS_FILE.exists():
        _API_KEYS_FILE.write_text("")
    return {ln.strip() for ln in _API_KEYS_FILE.read_text().splitlines() if ln.strip()}


def _get_client_ip(request: Request) -> str:
    cf_ip = request.headers.get("CF-Connecting-IP")
    if cf_ip:
        return cf_ip
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _check_rate_limit(ip: str) -> bool:
    """Return True if request is allowed, False if rate limit exceeded."""
    now = time.time()
    with _rate_lock:
        count, window_start = _rate_store.get(ip, (0, now))
        if now - window_start >= RATE_WINDOW:
            # Evict all expired entries on window reset to bound memory use
            expired = [k for k, (_, ws) in _rate_store.items() if now - ws >= RATE_WINDOW]
            for k in expired:
                del _rate_store[k]
            _rate_store[ip] = (1, now)
            return True
        if count >= RATE_LIMIT:
            return False
        _rate_store[ip] = (count + 1, window_start)
        return True


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.run_migrations()
    global _api_keys
    _api_keys = _load_api_keys()
    yield


app = FastAPI(lifespan=lifespan)
app.include_router(admin_router)


@app.middleware("http")
async def rate_limit_and_cache(request: Request, call_next):
    # Rate limiting on /api/inscriptions and /api/stats endpoints
    if request.url.path.startswith("/api/inscriptions") or request.url.path.startswith("/api/stats"):
        api_key = request.headers.get("X-API-Key", "")
        if api_key not in _api_keys or not _api_keys:
            ip = _get_client_ip(request)
            if not _check_rate_limit(ip):
                return Response(
                    content='{"detail":"Rate limit exceeded. 60 requests/minute. '
                            'Use X-API-Key header for higher limits."}',
                    status_code=429,
                    media_type="application/json",
                )

    response = await call_next(request)
    # Tile responses set their own cache header; everything else gets no-store
    if request.url.path.startswith("/api/") and not request.url.path.startswith("/api/tiles/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/api/tiles/{z}/{x}/{y}")
def tiles(
    z: float, x: int, y: int,
    gender: str | None = None,
    confidence: str | None = None,
    hide_deity: bool = False,
    hide_imperial: bool = False,
    has_translation: bool = False,
    search: str | None = None,
    date_from: int | None = None,
    date_to: int | None = None,
    exclude_undated: bool = False,
):
    data = db.get_markers_for_tile(
        int(z), x, y,
        gender=gender,
        confidence=confidence,
        hide_deity=hide_deity,
        hide_imperial=hide_imperial,
        has_translation=has_translation,
        search=search,
        date_from=date_from,
        date_to=date_to,
        exclude_undated=exclude_undated,
    )
    response = JSONResponse(content=data)
    if gender or confidence or hide_deity or hide_imperial or has_translation or search \
            or date_from is not None or date_to is not None or exclude_undated:
        response.headers["Cache-Control"] = "no-store"
    else:
        response.headers["Cache-Control"] = "public, max-age=86400"
    return response


@app.get("/api/inscription/{edcs_id}")
def inscription(edcs_id: str):
    result = db.get_inscription(edcs_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Inscription not found")
    return result


@app.get("/api/cluster/{cluster_id}")
def cluster_inscriptions(cluster_id: int, province: str):
    rows = db.get_cluster_inscriptions(cluster_id, province)
    if not rows:
        raise HTTPException(status_code=404, detail="Cluster not found")
    return {"cluster_id": cluster_id, "count": len(rows), "inscriptions": rows}


@app.get("/api/global-cluster/{global_cluster_id}")
def global_cluster_inscriptions(global_cluster_id: int):
    rows = db.get_global_cluster_inscriptions(global_cluster_id)
    if not rows:
        raise HTTPException(status_code=404, detail="Global cluster not found")
    provinces = sorted({r["province"] for r in rows})
    return {
        "global_cluster_id": global_cluster_id,
        "count": len(rows),
        "province_count": len(provinces),
        "provinces": provinces,
        "inscriptions": rows,
    }


@app.post("/api/flags")
def flag(req: FlagRequest):
    db.insert_flag(req.edcs_id, req.category, req.comment, req.email)
    return {"ok": True}


@app.get("/api/provinces")
def provinces():
    return db.get_provinces()


@app.get("/api/inscriptions")
def search_inscriptions(
    nomen: str | None = None,
    cognomen: str | None = None,
    praenomen: str | None = None,
    q: str | None = None,
    province: str | None = None,
    date_from: int | None = None,
    date_to: int | None = None,
    gender: str | None = None,
    inscription_type: str | None = None,
    page: int = 1,
    limit: int = 50,
    view: str = "inscriptions",
    format: str = "json",
):
    limit = min(max(1, limit), 200)
    page = max(1, page)
    total, results = db.search_inscriptions(
        nomen=nomen, cognomen=cognomen, praenomen=praenomen,
        q=q, province=province, date_from=date_from, date_to=date_to,
        gender=gender, inscription_type=inscription_type,
        page=page, limit=limit, view=view,
    )
    if format == "csv":
        csv_data = db.results_to_csv(results, view)
        return Response(
            content=csv_data,
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=roman_names_export.csv"},
        )
    return {"total": total, "page": page, "limit": limit, "results": results}


@app.get("/api/inscriptions/{edcs_id}")
def inscription_by_id(edcs_id: str):
    result = db.get_inscription(edcs_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Inscription not found")
    return result


@app.get("/api/stats/names")
def name_stats(
    nomen: str | None = None,
    province: str | None = None,
    date_from: int | None = None,
    date_to: int | None = None,
):
    return db.get_name_stats(
        nomen=nomen, province=province,
        date_from=date_from, date_to=date_to,
    )


@app.get("/search")
def search_page():
    return FileResponse(WEBAPP_DIR / "search.html")


@app.get("/attribution")
def attribution_page():
    return FileResponse(WEBAPP_DIR / "attribution.html")


# Static files mount must come last — it catches everything not matched above
app.mount("/", StaticFiles(directory=WEBAPP_DIR, html=True), name="static")
