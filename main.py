import logging
import os
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from database import init_db
from routers import auth
from routers.initiatives import router as initiatives_router
from routers.tasks import router as tasks_router
from routers.distribution import router as distribution_router
from routers.revenue import router as revenue_router
from routers.copilot import router as copilot_router

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


@app.on_event("startup")
async def startup():
    try:
        init_db()
        log.info("MyTodo Founder OS started — database ready")
    except Exception as e:
        log.error(f"MyTodo startup — database init failed: {e}")


@app.exception_handler(303)
async def redirect_handler(request: Request, exc):
    return RedirectResponse(url=exc.headers["Location"], status_code=303)


@app.get("/")
async def root():
    return RedirectResponse(url="/copilot", status_code=302)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "mytodo-founder-os"}
