import logging
import os
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from database import init_db, bootstrap_founder
from routers import auth
from routers.initiatives import router as initiatives_router
from routers.tasks import router as tasks_router
from routers.distribution import router as distribution_router
from routers.revenue import router as revenue_router
from routers.copilot import router as copilot_router
from routers.users import router as users_router

BASE_DIR = Path(__file__).parent

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("mytodo")

app = FastAPI(title="MyTodo Founder OS", docs_url=None, redoc_url=None)

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

app.include_router(auth.router)
app.include_router(copilot_router)
app.include_router(initiatives_router)
app.include_router(tasks_router)
app.include_router(distribution_router)
app.include_router(revenue_router)
app.include_router(users_router)

# ── PHANT intelligence layer (optional) ──────────────────────────────────────
# PHANT is an optional intelligence overlay. If the phant package is absent,
# all product functionality continues. Only PHANT endpoints and UI disappear.
_PHANT_ROUTERS = [
    "phant.routers.chat_router",
    "phant.routers.memory_router",
    "phant.routers.decision_router",
    "phant.routers.event_router",
    "phant.routers.brief_router",
    "phant.routers.context_router",
    "phant.routers.divergence_router",
    "phant.routers.constraint_router",
    "phant.routers.signals_router",
    "phant.routers.pages_router",
]

_phant_loaded = False
try:
    import importlib
    for _mod_path in _PHANT_ROUTERS:
        _mod = importlib.import_module(_mod_path)
        app.include_router(_mod.router)
    _phant_loaded = True
    log.info("PHANT intelligence layer loaded (%d routers)", len(_PHANT_ROUTERS))
except Exception as _phant_err:
    log.warning("PHANT not loaded — product continues without intelligence layer: %s", _phant_err)


@app.on_event("startup")
async def startup():
    try:
        init_db()
        log.info("MyTodo Founder OS started — database ready")
        bootstrap_founder()
        log.info("Founder bootstrap complete")
    except Exception as e:
        log.error(f"MyTodo startup error: {e}")


@app.exception_handler(303)
async def redirect_handler(request: Request, exc):
    return RedirectResponse(url=exc.headers["Location"], status_code=303)


@app.get("/")
async def root():
    return RedirectResponse(url="/copilot", status_code=302)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "mytodo-founder-os"}


@app.get("/debug/schema")
async def debug_schema():
    """Temporary: show which columns exist in each product table."""
    from database import engine
    from sqlalchemy import text, inspect as sa_inspect
    try:
        inspector = sa_inspect(engine)
        tables = ["initiatives", "tasks", "revenue_records", "distribution_actions"]
        result = {}
        for t in tables:
            try:
                cols = [c["name"] for c in inspector.get_columns(t)]
                result[t] = cols
            except Exception as e:
                result[t] = f"ERROR: {e}"
        return result
    except Exception as e:
        return {"error": str(e)}
