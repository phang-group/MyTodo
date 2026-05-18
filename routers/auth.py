from pathlib import Path
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
import gateway_auth

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str = ""):
    return templates.TemplateResponse("login.html", {"request": request, "error": error})


@router.post("/login")
async def login(
    request: Request,
    password: str = Form(...),
):
    if not gateway_auth.check_access_code(password):
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Incorrect access code"},
            status_code=401,
        )
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(
        gateway_auth.COOKIE_NAME,
        gateway_auth.make_session_cookie(),
        httponly=True,
        max_age=86400 * 30,
        samesite="lax",
        secure=True,
    )
    return response


@router.post("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(gateway_auth.COOKIE_NAME)
    return response
