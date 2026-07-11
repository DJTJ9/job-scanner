"""FastAPI-Web-UI: Login, Profilwahl, Dashboard, Profil-Wizard. Nur create_app() exportieren —
kein Modul-Level app-Objekt, sonst würde jeder Test-Import storage.init_db() gegen die
echte data/jobs.db als Seiteneffekt auslösen."""
from __future__ import annotations

import hmac
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from jobscanner import config, storage

_DIR = Path(__file__).parent
_DEFAULT_DB = Path(__file__).parent.parent.parent / "data" / "jobs.db"


def create_app(db_path: str | Path | None = None) -> FastAPI:
    settings = config.load_web_settings()
    storage.init_db(db_path or _DEFAULT_DB)
    storage.migrate_yaml_profile()

    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key=settings["session_secret"])
    app.mount("/static", StaticFiles(directory=_DIR / "static"), name="static")
    templates = Jinja2Templates(directory=_DIR / "templates")

    def require_login(request: Request) -> RedirectResponse | None:
        if not request.session.get("authenticated"):
            return RedirectResponse("/login", status_code=303)
        return None

    @app.get("/login")
    def login_form(request: Request):
        return templates.TemplateResponse(request, "login.html", {"error": None})

    @app.post("/login")
    def login_submit(request: Request, password: str = Form(...)):
        if hmac.compare_digest(password, settings["password"]):
            request.session["authenticated"] = True
            return RedirectResponse("/", status_code=303)
        return templates.TemplateResponse(
            request, "login.html", {"error": "Falsches Passwort"}, status_code=401)

    @app.get("/logout")
    def logout(request: Request):
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    @app.get("/")
    def profiles_view(request: Request):
        if (redirect := require_login(request)) is not None:
            return redirect
        return templates.TemplateResponse(
            request, "profiles.html", {"profiles": storage.list_profiles(active_only=True)})

    return app
