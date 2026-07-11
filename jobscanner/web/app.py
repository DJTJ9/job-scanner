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

    @app.get("/dashboard/{profile_id}")
    def dashboard(request: Request, profile_id: int):
        if (redirect := require_login(request)) is not None:
            return redirect
        profile = storage.get_profile(profile_id)
        if profile is None:
            return RedirectResponse("/", status_code=303)
        return templates.TemplateResponse(request, "dashboard.html", {
            "profile": profile,
            "criteria": storage.list_criteria(profile_id),
            "entries": storage.list_jobs_with_scores(profile_id),
            "feedback": storage.get_feedback_map(profile_id),
        })

    @app.post("/dashboard/{profile_id}/criteria")
    async def save_criteria_route(request: Request, profile_id: int):
        if (redirect := require_login(request)) is not None:
            return redirect
        form = await request.form()
        existing = storage.list_criteria(profile_id)
        updated = [
            {"key": c["key"], "label": c["label"], "sort": c["sort"],
             "weight": int(form.get(f"weight_{c['key']}", c["weight"]))}
            for c in existing
        ]
        storage.save_criteria(profile_id, updated)
        return RedirectResponse(f"/dashboard/{profile_id}", status_code=303)

    @app.post("/dashboard/{profile_id}/feedback/{fingerprint}")
    async def feedback_route(request: Request, profile_id: int, fingerprint: str):
        if (redirect := require_login(request)) is not None:
            return redirect
        form = await request.form()
        vote = form.get("vote")
        if vote in ("up", "down"):
            storage.add_feedback(profile_id, fingerprint, vote)
        return RedirectResponse(f"/dashboard/{profile_id}", status_code=303)

    return app
