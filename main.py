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
from phant.routers.chat_router       import router as phant_chat_router
from phant.routers.memory_router     import router as phant_memory_router
from phant.routers.decision_router   import router as phant_decision_router
from phant.routers.event_router      import router as phant_event_router
from phant.routers.brief_router      import router as phant_brief_router
from phant.routers.context_router    import router as phant_context_router
from phant.routers.divergence_router import router as phant_divergence_router
from phant.routers.constraint_router import router as phant_constraint_router
from phant.routers.signals_router    import router as phant_signals_router
from phant.routers.pages_router      import router as phant_pages_router

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
# PHANT intelligence layer
app.include_router(phant_chat_router)
app.include_router(phant_memory_router)
app.include_router(phant_decision_router)
app.include_router(phant_event_router)
app.include_router(phant_brief_router)
app.include_router(phant_context_router)
app.include_router(phant_divergence_router)
app.include_router(phant_constraint_router)
app.include_router(phant_signals_router)
app.include_router(phant_pages_router)


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
