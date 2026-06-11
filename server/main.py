from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import db
from .admin import router as admin_router
from .models import FlagRequest


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.run_migrations()
    yield


app = FastAPI(lifespan=lifespan)
app.include_router(admin_router)

WEBAPP_DIR = Path(__file__).parent.parent / "webapp"


@app.middleware("http")
async def cache_control(request: Request, call_next):
    response = await call_next(request)
    # Tile responses set their own cache header; everything else gets no-store
    if request.url.path.startswith("/api/") and not request.url.path.startswith("/api/tiles/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/api/tiles/{z}/{x}/{y}")
def tiles(
    z: int, x: int, y: int,
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
        z, x, y,
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
def cluster_inscriptions(cluster_id: int):
    rows = db.get_cluster_inscriptions(cluster_id)
    return {"cluster_id": cluster_id, "count": len(rows), "inscriptions": rows}


@app.post("/api/flags")
def flag(req: FlagRequest):
    db.insert_flag(req.edcs_id, req.category, req.comment, req.email)
    return {"ok": True}


# Static files mount must come last — it catches everything not matched above
app.mount("/", StaticFiles(directory=WEBAPP_DIR, html=True), name="static")
