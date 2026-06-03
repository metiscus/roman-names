from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import db
from .models import FlagRequest

app = FastAPI()

WEBAPP_DIR = Path(__file__).parent.parent / "webapp"


@app.middleware("http")
async def cache_control(request: Request, call_next):
    response = await call_next(request)
    # Tile responses set their own cache header; everything else gets no-store
    if request.url.path.startswith("/api/") and not request.url.path.startswith("/api/tiles/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/api/tiles/{z}/{x}/{y}")
def tiles(z: int, x: int, y: int):
    data = db.get_markers_for_tile(z, x, y)
    response = JSONResponse(content=data)
    response.headers["Cache-Control"] = "public, max-age=86400"
    return response


@app.get("/api/inscription/{edcs_id}")
def inscription(edcs_id: str):
    result = db.get_inscription(edcs_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Inscription not found")
    return result


@app.post("/api/flags")
def flag(req: FlagRequest):
    db.insert_flag(req.edcs_id, req.category, req.comment, req.email)
    return {"ok": True}


# Static files mount must come last — it catches everything not matched above
app.mount("/", StaticFiles(directory=WEBAPP_DIR, html=True), name="static")
