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
from jobscanner.web import llm_refine

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

    STEP_ORDER = ["basis", "skills", "zielrollen", "ort_umfang", "no_gos", "gewichte"]

    def _split(text: str) -> list[str]:
        return [t.strip() for t in text.split(",") if t.strip()]

    def _wizard_state(request: Request) -> dict:
        return request.session.setdefault("wizard", {"data": {}, "suggestions": {}})

    @app.get("/wizard/new")
    def wizard_start(request: Request):
        if (redirect := require_login(request)) is not None:
            return redirect
        request.session["wizard"] = {"data": {}, "suggestions": {}}
        return RedirectResponse(f"/wizard/{STEP_ORDER[0]}", status_code=303)

    @app.get("/wizard/{step}")
    def wizard_step_form(request: Request, step: str):
        if (redirect := require_login(request)) is not None:
            return redirect
        if step not in STEP_ORDER:
            return RedirectResponse("/wizard/new", status_code=303)
        wizard = _wizard_state(request)
        return templates.TemplateResponse(request, "wizard.html", {
            "step": step, "step_order": STEP_ORDER,
            "data": wizard["data"], "suggestions": wizard.get("suggestions", {}),
            "default_criteria": storage.DEFAULT_CRITERIA,
        })

    @app.post("/wizard/llm-refine")
    async def wizard_llm_refine(request: Request):
        if (redirect := require_login(request)) is not None:
            return redirect
        form = await request.form()
        freetext = form.get("freetext", "")
        wizard = _wizard_state(request)
        if freetext.strip():
            try:
                wizard["suggestions"] = llm_refine.suggest_from_freetext(freetext)
            except Exception as exc:
                wizard["suggestions"] = {"error": str(exc)}
        request.session["wizard"] = wizard
        return RedirectResponse("/wizard/skills", status_code=303)

    @app.post("/wizard/{step}")
    async def wizard_step_submit(request: Request, step: str):
        if (redirect := require_login(request)) is not None:
            return redirect
        if step not in STEP_ORDER:
            return RedirectResponse("/wizard/new", status_code=303)
        form = await request.form()
        wizard = _wizard_state(request)
        data = wizard["data"]
        if step == "basis":
            data["name"] = form.get("name", "").strip()
            data["level"] = form.get("level", "").strip()
            data["experience_years"] = int(form.get("experience_years") or 0)
        elif step == "skills":
            skills = set(_split(form.get("skills", "")))
            skills.update(form.getlist("suggested_skills"))
            data["skills"] = sorted(skills)
        elif step == "zielrollen":
            roles = set(_split(form.get("target_roles", "")))
            roles.update(form.getlist("suggested_roles"))
            data["target_roles"] = sorted(roles)
        elif step == "ort_umfang":
            data["location"] = form.get("location", "").strip()
            data["employment"] = form.get("employment", "").strip()
            data["languages"] = _split(form.get("languages", "de"))
        elif step == "no_gos":
            data["no_gos"] = _split(form.get("no_gos", ""))
        elif step == "gewichte":
            criteria = [
                {"key": c["key"], "label": c["label"], "sort": i,
                 "weight": int(form.get(f"weight_{c['key']}", c["weight"]))}
                for i, c in enumerate(storage.DEFAULT_CRITERIA)
            ]
            data.setdefault("experience_sources", [])
            data.setdefault("portfolio", [])
            name = data.pop("name", "") or f"Profil {len(storage.list_profiles()) + 1}"
            pid = storage.create_profile(name, data, queries=None)
            storage.save_criteria(pid, criteria)
            request.session.pop("wizard", None)
            return RedirectResponse(f"/dashboard/{pid}", status_code=303)
        request.session["wizard"] = wizard
        next_step = STEP_ORDER[STEP_ORDER.index(step) + 1]
        return RedirectResponse(f"/wizard/{next_step}", status_code=303)

    return app
