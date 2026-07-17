"""FastAPI-Web-UI: Login, Profilwahl, Dashboard, Profil-Wizard. Nur create_app() exportieren —
kein Modul-Level app-Objekt, sonst würde jeder Test-Import storage.init_db() gegen die
echte data/jobs.db als Seiteneffekt auslösen."""
from __future__ import annotations

import hmac
import subprocess
import threading
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool
from starlette.middleware.sessions import SessionMiddleware

from jobscanner import config, nocodb_board, scoring, storage
from jobscanner.web import llm_refine, mcp_api

_DIR = Path(__file__).parent
_DEFAULT_DB = Path(__file__).parent.parent.parent / "data" / "jobs.db"
_REPO_ROOT = Path(__file__).parent.parent.parent


def _read_asset_version(base_dir: Path) -> str:
    """Git-Short-Hash als Cache-Busting-Version für /static/-Refs. Fallback 'unknown' bei Fehler/kein Git-Repo."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=base_dir,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return "unknown"


def create_app(db_path: str | Path | None = None) -> FastAPI:
    settings = config.load_web_settings()
    storage.init_db(db_path or _DEFAULT_DB)
    storage.migrate_yaml_profile()
    if settings["owner_email"]:
        storage.seed_owner(settings["owner_email"], settings["password"])

    mcp_server = mcp_api.create_mcp_server()
    mcp_asgi = mcp_server.streamable_http_app()

    @asynccontextmanager
    async def lifespan(app):
        async with mcp_server.session_manager.run():
            yield

    app = FastAPI(lifespan=lifespan)

    @app.middleware("http")
    async def log_pageview(request: Request, call_next):
        if request.scope["path"] == "/mcp":
            # Exakt "/mcp" würde der Router per 307 auf "/mcp/" umleiten, bevor die
            # Token-Auth läuft — hinter Caddy verliert der Redirect das https-Schema.
            request.scope["path"] = "/mcp/"
        if not request.url.path.startswith(("/static/", "/mcp")):
            storage.log_event("pageview", user_id=request.session.get("user_id"),
                              meta={"path": request.url.path})
        return await call_next(request)

    app.add_middleware(SessionMiddleware, secret_key=settings["session_secret"])
    app.mount("/static", StaticFiles(directory=_DIR / "static"), name="static")
    app.mount("/mcp", mcp_api.TokenAuthMiddleware(mcp_asgi))
    templates = Jinja2Templates(directory=_DIR / "templates")
    templates.env.globals["asset_version"] = _read_asset_version(_DIR)

    def require_user(request: Request) -> RedirectResponse | None:
        if request.session.get("user_id") is None:
            return RedirectResponse("/login", status_code=303)
        return None

    def require_owner(request: Request) -> RedirectResponse | JSONResponse | None:
        if request.session.get("user_id") is None:
            return RedirectResponse("/login", status_code=303)
        if request.session.get("role") != "owner":
            return JSONResponse({"error": "forbidden"}, status_code=403)
        return None

    def _require_owned(request: Request, profile_id: int):
        """(profile, None) wenn eingeloggt UND Profil dem User gehört; sonst (None, response).
        Unbekanntes Profil → Redirect /; fremdes Profil → 404."""
        if (redirect := require_user(request)) is not None:
            return None, redirect
        profile = storage.get_profile(profile_id)
        if profile is None:
            return None, RedirectResponse("/", status_code=303)
        if profile.get("user_id") != request.session.get("user_id"):
            return None, JSONResponse({"error": "not found"}, status_code=404)
        return profile, None

    @app.get("/login")
    def login_form(request: Request):
        return templates.TemplateResponse(request, "login.html", {"error": None})

    @app.post("/login")
    def login_submit(request: Request, email: str = Form(...), password: str = Form(...)):
        user = storage.verify_password(email, password)
        if user is not None:
            request.session["user_id"] = user["id"]
            request.session["email"] = user["email"]
            request.session["role"] = user["role"]
            return RedirectResponse("/", status_code=303)
        return templates.TemplateResponse(
            request, "login.html", {"error": "Falsche Zugangsdaten"}, status_code=401)

    @app.get("/logout")
    def logout(request: Request):
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    @app.get("/impressum")
    def impressum_view(request: Request):
        return templates.TemplateResponse(request, "impressum.html", {})

    @app.get("/datenschutz")
    def datenschutz_view(request: Request):
        return templates.TemplateResponse(request, "datenschutz.html", {})

    @app.get("/account/passwort")
    def account_password_form(request: Request):
        if (redirect := require_user(request)) is not None:
            return redirect
        return templates.TemplateResponse(
            request, "account_password.html", {"error": None, "success": None})

    @app.post("/account/passwort")
    def account_password_submit(
        request: Request,
        current_password: str = Form(...),
        new_password: str = Form(...),
        new_password_repeat: str = Form(...),
    ):
        if (redirect := require_user(request)) is not None:
            return redirect
        email = request.session.get("email")

        def _err(msg):
            return templates.TemplateResponse(
                request, "account_password.html",
                {"error": msg, "success": None}, status_code=400)

        if storage.verify_password(email, current_password) is None:
            return _err("Aktuelles Passwort ist falsch")
        if new_password != new_password_repeat:
            return _err("Passwörter stimmen nicht überein")
        if len(new_password) < 6:
            return _err("Neues Passwort muss mindestens 6 Zeichen haben")
        storage.set_password(request.session.get("user_id"), new_password)
        return templates.TemplateResponse(
            request, "account_password.html",
            {"error": None, "success": "Passwort geändert"})

    @app.get("/register")
    def register_form(request: Request):
        return templates.TemplateResponse(request, "register.html", {"error": None})

    @app.post("/register")
    def register_submit(request: Request, email: str = Form(...),
                        password: str = Form(...), invite_code: str = Form(...)):
        if not settings["invite_code"] or not hmac.compare_digest(
                invite_code, settings["invite_code"]):
            return templates.TemplateResponse(
                request, "register.html", {"error": "Ungültiger Invite-Code"}, status_code=403)
        email = email.strip().lower()
        if storage.get_user_by_email(email) is not None:
            return templates.TemplateResponse(
                request, "register.html", {"error": "Email bereits registriert"}, status_code=409)
        uid = storage.create_user(email, password, role="member")
        request.session["user_id"] = uid
        request.session["email"] = email
        request.session["role"] = "member"
        return RedirectResponse("/", status_code=303)

    @app.get("/")
    def profiles_view(request: Request):
        if (redirect := require_user(request)) is not None:
            return redirect
        profiles = storage.list_profiles(active_only=True,
                                          user_id=request.session.get("user_id"))
        return templates.TemplateResponse(request, "profiles.html", {
            "profiles": profiles,
            "profile_exists": len(profiles) > 0})

    @app.post("/profiles/{profile_id}/delete")
    def delete_profile_route(request: Request, profile_id: int):
        _profile, resp = _require_owned(request, profile_id)
        if resp is not None:
            return resp
        storage.delete_profile(profile_id)
        return RedirectResponse("/", status_code=303)

    @app.post("/profiles/api-token")
    def create_api_token_route(request: Request):
        if (redirect := require_user(request)) is not None:
            return redirect
        token = storage.create_api_token(request.session["user_id"])
        profiles = storage.list_profiles(active_only=True,
                                          user_id=request.session.get("user_id"))
        return templates.TemplateResponse(request, "profiles.html", {
            "profiles": profiles,
            "profile_exists": len(profiles) > 0,
            "api_token": token})

    _DASHBOARD_TABS = ("aktiv", "no_go", "bewertet")
    _FUNNEL_STEPS = (("onboarding_start", "Onboarding-Start"),
                     ("profil_erstellt", "Profil erstellt"),
                     ("feedback_gegeben", "Feedback gegeben"))
    _WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]

    @app.get("/dashboard/{profile_id}")
    def dashboard(request: Request, profile_id: int, tab: str = "aktiv"):
        profile, resp = _require_owned(request, profile_id)
        if resp is not None:
            return resp
        if tab not in _DASHBOARD_TABS:
            tab = "aktiv"
        feedback = storage.get_feedback_map(profile_id)
        aktiv, no_go, bewertet = [], [], []
        for entry in storage.list_jobs_with_scores(profile_id):
            fp = entry["job"].fingerprint
            if feedback.get(fp) == "down":
                bewertet.append(entry)
            elif entry["category"] == "No-Go":
                no_go.append(entry)
            else:
                aktiv.append(entry)
        entries_by_tab = {"aktiv": aktiv, "no_go": no_go, "bewertet": bewertet}
        analysis = storage.get_latest_analysis(profile_id)
        return templates.TemplateResponse(request, "dashboard.html", {
            "profile": profile,
            "criteria": storage.list_criteria(profile_id),
            "entries": entries_by_tab[tab],
            "feedback": feedback,
            "tab": tab,
            "counts": {"aktiv": len(aktiv), "no_go": len(no_go), "bewertet": len(bewertet)},
            "analysis": analysis,
            "proposed_insights": storage.list_insights(profile_id, status="proposed"),
            "active_insights": storage.list_insights(profile_id, status="confirmed"),
            "vote_count": len(feedback),
        })

    @app.get("/dashboard/{profile_id}/metriken")
    def metrics_view(request: Request, profile_id: int):
        if (resp := require_owner(request)) is not None:
            return resp
        profile, resp = _require_owned(request, profile_id)
        if resp is not None:
            return resp
        metrics = storage.get_metrics_summary()
        funnel_counts = metrics["funnel_counts"]
        max_count = funnel_counts.get("onboarding_start", 0) or 1
        funnel_steps = []
        prev_count = None
        for key, label in _FUNNEL_STEPS:
            count = funnel_counts.get(key, 0)
            drop = round((1 - count / prev_count) * 100) if prev_count else None
            funnel_steps.append({
                "label": label, "count": count,
                "pct": round(count / max_count * 100),
                "drop": drop,
            })
            prev_count = count or None
        feedback_rate = (
            round(funnel_counts["feedback_gegeben"] / funnel_counts["profil_erstellt"] * 100)
            if funnel_counts.get("profil_erstellt") else 0)
        daily = storage.get_daily_event_counts()
        max_daily = max((d["count"] for d in daily), default=0) or 1
        daily_counts = [
            {"day": d["day"], "count": d["count"],
             "height_pct": round(d["count"] / max_daily * 100),
             "weekday": _WEEKDAYS[date.fromisoformat(d["day"]).weekday()]}
            for d in daily
        ]
        return templates.TemplateResponse(request, "metrics.html", {
            "profile": profile,
            "metrics": metrics,
            "feedback_rate": feedback_rate,
            "funnel_steps": funnel_steps,
            "daily_counts": daily_counts,
        })

    @app.post("/dashboard/{profile_id}/criteria")
    async def save_criteria_route(request: Request, profile_id: int):
        _profile, resp = _require_owned(request, profile_id)
        if resp is not None:
            return resp
        form = await request.form()
        existing = storage.list_criteria(profile_id)
        updated = [
            {"key": c["key"], "label": c["label"], "sort": c["sort"],
             "weight": int(form.get(f"weight_{c['key']}", c["weight"]))}
            for c in existing
        ]
        storage.save_criteria(profile_id, updated)
        if request.session.get("role") == "owner":
            changed = storage.rescore_profile(profile_id)
            if changed:
                def _push_changed(fingerprints: list[str]) -> None:
                    for fp in fingerprints:
                        job = storage.get_job(fp)
                        if job is not None:
                            try:
                                nocodb_board.push_job(job)
                            except Exception:
                                pass
                threading.Thread(target=_push_changed, args=(changed,), daemon=True).start()
        else:
            storage.score_profile_deterministic(profile_id)
        return RedirectResponse(f"/dashboard/{profile_id}", status_code=303)

    @app.post("/dashboard/{profile_id}/feedback/{fingerprint}")
    async def feedback_route(request: Request, profile_id: int, fingerprint: str):
        _profile, resp = _require_owned(request, profile_id)
        if resp is not None:
            return resp
        form = await request.form()
        vote = form.get("vote")
        if vote in ("up", "down"):
            storage.add_feedback(profile_id, fingerprint, vote)
            storage.log_event("feedback_gegeben", user_id=request.session.get("user_id"))
        else:
            vote = None
        if "application/json" in request.headers.get("accept", ""):
            return JSONResponse({"vote": vote, "fingerprint": fingerprint})
        return RedirectResponse(f"/dashboard/{profile_id}", status_code=303)

    _FEEDBACK_CONFIRMATION = "Bob hat's notiert. Danke!"

    @app.post("/api/feedback")
    async def member_feedback_route(request: Request):
        user_id = request.session.get("user_id")
        if user_id is None:
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        body = await request.json()
        text = (body.get("text") or "").strip()
        if not text:
            return JSONResponse({"error": "Text fehlt"}, status_code=400)
        storage.create_member_feedback(user_id, text)
        return JSONResponse({"message": _FEEDBACK_CONFIRMATION})

    @app.get("/admin/feedback")
    def admin_feedback_view(request: Request):
        if (resp := require_owner(request)) is not None:
            return resp
        return templates.TemplateResponse(request, "admin_feedback.html", {
            "feedback_entries": storage.list_member_feedback(),
        })

    def _launch_feedback_agent(pass_name: str, analysis_id: int) -> None:
        try:
            subprocess.Popen(
                ["bash", "deploy/run_feedback_agent.sh", pass_name, str(analysis_id)],
                cwd=_REPO_ROOT,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

    @app.post("/dashboard/{profile_id}/analyze")
    def analyze_votes(request: Request, profile_id: int):
        if (resp := require_owner(request)) is not None:
            return resp
        _profile, resp = _require_owned(request, profile_id)
        if resp is not None:
            return resp
        analysis_id = storage.create_analysis(profile_id)
        _launch_feedback_agent("analyze", analysis_id)
        return RedirectResponse(f"/dashboard/{profile_id}", status_code=303)

    @app.get("/dashboard/{profile_id}/analysis")
    def analysis_status(request: Request, profile_id: int):
        if (resp := require_owner(request)) is not None:
            return resp
        _profile, resp = _require_owned(request, profile_id)
        if resp is not None:
            return resp
        analysis = storage.get_latest_analysis(profile_id)
        if analysis is None:
            return JSONResponse({"status": None})
        return JSONResponse({"id": analysis["id"], "status": analysis["status"],
                             "cards": analysis["cards"]})

    @app.post("/dashboard/{profile_id}/analysis/answers")
    async def save_answers(request: Request, profile_id: int):
        if (resp := require_owner(request)) is not None:
            return resp
        _profile, resp = _require_owned(request, profile_id)
        if resp is not None:
            return resp
        body = await request.json()
        storage.save_analysis_answers(body["analysis_id"], body.get("answers", {}))
        return JSONResponse({"ok": True})

    @app.post("/dashboard/{profile_id}/finalize")
    def finalize_analysis(request: Request, profile_id: int):
        if (resp := require_owner(request)) is not None:
            return resp
        _profile, resp = _require_owned(request, profile_id)
        if resp is not None:
            return resp
        analysis = storage.get_latest_analysis(profile_id)
        if analysis is not None:
            storage.set_analysis_status(analysis["id"], "synthesizing")
            _launch_feedback_agent("synthesize", analysis["id"])
        return RedirectResponse(f"/dashboard/{profile_id}", status_code=303)

    @app.post("/dashboard/{profile_id}/insights/{insight_id}/confirm")
    def confirm_insight_route(request: Request, profile_id: int, insight_id: int):
        if (resp := require_owner(request)) is not None:
            return resp
        _profile, resp = _require_owned(request, profile_id)
        if resp is not None:
            return resp
        storage.confirm_insight(insight_id)
        return RedirectResponse(f"/dashboard/{profile_id}", status_code=303)

    @app.post("/dashboard/{profile_id}/insights/{insight_id}/reject")
    def reject_insight_route(request: Request, profile_id: int, insight_id: int):
        if (resp := require_owner(request)) is not None:
            return resp
        _profile, resp = _require_owned(request, profile_id)
        if resp is not None:
            return resp
        storage.reject_insight(insight_id)
        return RedirectResponse(f"/dashboard/{profile_id}", status_code=303)

    @app.post("/dashboard/{profile_id}/apply")
    def apply_insights(request: Request, profile_id: int):
        if (resp := require_owner(request)) is not None:
            return resp
        _profile, resp = _require_owned(request, profile_id)
        if resp is not None:
            return resp
        # Gewichts-Insights sind schon in criteria → deterministischer Rescore, sofort.
        changed = storage.rescore_profile(profile_id)
        # Freitext-Präferenzen → bestehende Jobs für LLM-Rescore enqueuen + Scoring-Agent starten.
        has_preference = any(
            i["kind"] == "preference"
            for i in storage.list_insights(profile_id, status="confirmed"))
        if has_preference:
            storage.enqueue_jobs_for_rescore(profile_id)
            try:
                subprocess.Popen(
                    ["bash", "deploy/run_scoring_agent.sh"],
                    cwd=_REPO_ROOT,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass
        if changed:
            def _push_changed(fingerprints: list[str]) -> None:
                for fp in fingerprints:
                    job = storage.get_job(fp)
                    if job is not None:
                        try:
                            nocodb_board.push_job(job)
                        except Exception:
                            pass
            threading.Thread(target=_push_changed, args=(changed,), daemon=True).start()
        return RedirectResponse(f"/dashboard/{profile_id}", status_code=303)

    STEP_ORDER = ["basis", "skills", "zielrollen", "domaenen", "ort_umfang", "no_gos", "gewichte"]
    STEP_LABELS = {
        "basis": "Basics", "skills": "Skills", "zielrollen": "Zielrollen",
        "domaenen": "Domänen", "ort_umfang": "Ort und Umfang",
        "no_gos": "No-Gos", "gewichte": "Gewichte",
    }

    def _split(text: str) -> list[str]:
        return [t.strip() for t in text.split(",") if t.strip()]

    def _wizard_state(request: Request) -> dict:
        return request.session.setdefault("wizard", {"data": {}, "suggestions": {}})

    @app.get("/wizard/new")
    def wizard_start(request: Request):
        if (redirect := require_user(request)) is not None:
            return redirect
        request.session["wizard"] = {"data": {}, "suggestions": {}}
        storage.log_event("onboarding_start", user_id=request.session.get("user_id"))
        return RedirectResponse(f"/wizard/{STEP_ORDER[0]}", status_code=303)

    @app.get("/wizard/edit/{profile_id}")
    def wizard_edit(request: Request, profile_id: int):
        profile, resp = _require_owned(request, profile_id)
        if resp is not None:
            return resp
        data = dict(profile["data"])
        data["name"] = profile["name"]
        weights = {c["key"]: c["weight"] for c in storage.list_criteria(profile_id)}
        data["weights"] = weights
        request.session["wizard"] = {
            "data": data,
            "suggestions": {"criteria_weights": weights},
            "edit_id": profile_id,
        }
        return RedirectResponse(f"/wizard/{STEP_ORDER[0]}", status_code=303)

    @app.get("/wizard/{step}")
    def wizard_step_form(request: Request, step: str):
        if (redirect := require_user(request)) is not None:
            return redirect
        if step not in STEP_ORDER:
            return RedirectResponse("/wizard/new", status_code=303)
        wizard = _wizard_state(request)
        return templates.TemplateResponse(request, "wizard.html", {
            "step": step, "step_order": STEP_ORDER,
            "data": wizard["data"], "suggestions": wizard.get("suggestions", {}),
            "default_criteria": storage.DEFAULT_CRITERIA,
            "weights_catalog": scoring.WEIGHTS_CATALOG,
            "no_gos_catalog": scoring.NO_GOS_CATALOG,
            "role": request.session.get("role"),
            "step_labels": STEP_LABELS,
            "skill_suggestions": scoring.SKILL_SUGGESTIONS,
            "role_suggestions": scoring.ROLE_SUGGESTIONS,
            "domains_catalog": scoring.DOMAINS_CATALOG,
            "city_suggestions": scoring.CITY_SUGGESTIONS,
            "employment_options": scoring.EMPLOYMENT_OPTIONS,
            "language_options": scoring.LANGUAGE_OPTIONS,
            "prev_step": STEP_ORDER[STEP_ORDER.index(step) - 1] if STEP_ORDER.index(step) > 0 else None,
        })

    @app.post("/wizard/llm-refine")
    async def wizard_llm_refine(request: Request):
        if (resp := require_owner(request)) is not None:
            return resp
        if (redirect := require_user(request)) is not None:
            return redirect
        form = await request.form()
        freetext = form.get("freetext", "")
        wizard = _wizard_state(request)
        if freetext.strip():
            try:
                wizard["suggestions"] = await run_in_threadpool(
                    llm_refine.suggest_from_freetext, freetext)
            except Exception as exc:
                wizard["suggestions"] = {"error": str(exc)}
        request.session["wizard"] = wizard
        return RedirectResponse("/wizard/skills", status_code=303)

    @app.post("/wizard/{step}")
    async def wizard_step_submit(request: Request, step: str):
        if (redirect := require_user(request)) is not None:
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
        elif step == "domaenen":
            valid = {d["key"] for d in scoring.DOMAINS_CATALOG}
            data["domains"] = [k for k in form.getlist("domains") if k in valid]
        elif step == "ort_umfang":
            cities = set(_split(form.get("cities", "")))
            cities.update(form.getlist("suggested_cities"))
            data["cities"] = sorted(cities)
            data["employment_types"] = form.getlist("employment_types")
            langs = set(form.getlist("languages"))
            langs.update(_split(form.get("languages_free", "")))
            data["languages"] = sorted(langs)
        elif step == "no_gos":
            if request.session.get("role") == "owner":
                data["no_gos"] = _split(form.get("no_gos", ""))
            else:
                valid = {n["key"] for n in scoring.NO_GOS_CATALOG}
                data["no_gos"] = [k for k in form.getlist("no_gos") if k in valid]
        elif step == "gewichte":
            role = request.session.get("role")
            if role == "owner":
                catalog = [dict(c) for c in storage.DEFAULT_CRITERIA]
            else:
                catalog = [{"key": w["key"], "label": w["label"], "weight": w["default_weight"]}
                           for w in scoring.WEIGHTS_CATALOG]
            criteria = [
                {"key": c["key"], "label": c["label"], "sort": i,
                 "weight": int(form.get(f"weight_{c['key']}", 0))}
                for i, c in enumerate(catalog)
            ]
            data.setdefault("experience_sources", [])
            data.setdefault("portfolio", [])
            data.pop("weights", None)  # Prefill-Hilfsfeld, nicht persistieren
            name = data.pop("name", "") or f"Profil {len(storage.list_profiles()) + 1}"
            edit_id = wizard.get("edit_id")
            if edit_id is not None:
                storage.update_profile(edit_id, name, data)
                storage.save_criteria(edit_id, criteria)
                pid = edit_id
            else:
                pid = storage.create_profile(name, data, queries=None,
                                            user_id=request.session.get("user_id"))
                storage.save_criteria(pid, criteria)
                storage.log_event("profil_erstellt", user_id=request.session.get("user_id"))
            if role != "owner":
                storage.score_profile_deterministic(pid)
            request.session.pop("wizard", None)
            return RedirectResponse(f"/dashboard/{pid}", status_code=303)
        request.session["wizard"] = wizard
        next_step = STEP_ORDER[STEP_ORDER.index(step) + 1]
        return RedirectResponse(f"/wizard/{next_step}", status_code=303)

    return app
