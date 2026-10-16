"""FastAPI app: JSON API under /api, and the built React app for everything else.

One service, one URL: no CORS setup, nothing extra to deploy.
"""
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.app import db, trace

load_dotenv()

FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    db.close()


app = FastAPI(title="Miraflores Workpaper", lifespan=lifespan)
app.include_router(trace.router)


@app.get("/api/health")
def health():
    """Proves the whole chain works: app -> pool -> Neon -> loaded packet."""
    with db.pool().connection() as conn:
        tables = conn.execute(
            "SELECT count(*) AS n FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
        ).fetchone()["n"]
        counts = conn.execute(
            """
            SELECT
              (SELECT count(*) FROM documents)                            AS documents,
              (SELECT count(*) FROM extracted_values)                     AS extracted_values,
              (SELECT count(*) FROM return_lines WHERE version = 'v3')    AS lines_v3,
              (SELECT count(*) FROM findings WHERE status = 'open')       AS open_findings,
              (SELECT sha256 FROM packet_raw LIMIT 1)                     AS packet_sha256
            """
        ).fetchone()
    return {"status": "ok", "tables": tables, **counts}


# Serve the React build. Unknown paths return index.html so client-side
# routes (e.g. /lines/F1040.11) work on refresh.
if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        file = FRONTEND_DIST / path
        if path and file.is_file():
            return FileResponse(file)
        return FileResponse(FRONTEND_DIST / "index.html")
