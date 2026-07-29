"""FastAPI-Web-UI: Login, Profilwahl, Dashboard, Profil-Wizard. Nur create_app() exportieren —
kein Modul-Level app-Objekt, sonst würde jeder Test-Import storage.init_db() gegen die
echte data/jobs.db als Seiteneffekt auslösen."""
from __future__ import annotations

import hmac
import subprocess
import threading
import time
from contextlib import asynccontextmanager
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from jobscanner import browser, config, crypto, nocodb_board, precheck, scoring, storage
from jobscanner.web import csrf, llm_refine, mailer, mcp_api, rate_limit

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


def client_ip(request: Request) -> str:
    """Echte Client-IP hinter Caddy: rechtester X-Forwarded-For-Eintrag (der von
    Caddy angehängte Peer); linke Werte sind client-spoofbar und werden ignoriert.
    Fallback request.client.host, dann 'unknown'."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


def relzeit_datum(value: str | None) -> str:
    """Relatives Tages-Alter aus ISO-Datum YYYY-MM-DD: 'vor 3 Tagen (25.07.)'."""
    if not value:
        return ""
    d = date.fromisoformat(value)
    today = date.today()
    if d > today:  # Zukunft (sollte in Produktion nicht vorkommen) auf heute klemmen
        d = today
    delta = (today - d).days
    stamp = f"{d:%d.%m.}"
    if delta == 0:
        return f"heute ({stamp})"
    if delta == 1:
        return f"gestern ({stamp})"
    return f"vor {delta} Tagen ({stamp})"


def create_app(db_path: str | Path | None = None) -> FastAPI:
    settings = config.load_web_settings()
    crypto.require_key()
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
    app.state.rate_limiter = rate_limit.RateLimiter()
    app.state.resend_rate_limiter = rate_limit.RateLimiter(window_seconds=60, max_attempts=1)

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

    app.add_middleware(SessionMiddleware, secret_key=settings["session_secret"],
                       https_only=True, same_site="lax")
    app.mount("/static", StaticFiles(directory=_DIR / "static"), name="static")
    app.mount("/mcp", mcp_api.TokenAuthMiddleware(mcp_asgi))
    templates = Jinja2Templates(directory=_DIR / "templates")
    templates.env.globals["asset_version"] = _read_asset_version(_DIR)
    templates.env.globals["csrf_token"] = csrf.ensure_token

    def _wants_json(request: Request) -> bool:
        path = request.url.path
        if path.startswith("/api") or path.startswith("/mcp"):
            return True
        accept = request.headers.get("accept", "")
        return "application/json" in accept and "text/html" not in accept

    def _error_page(request: Request, code: int, title: str, message: str,
                    home_only: bool = False):
        return templates.TemplateResponse(
            request, "error.html",
            {"code": code, "title": title, "message": message, "home_only": home_only},
            status_code=code)

    def _csrf_error_page(request: Request):
        return _error_page(
            request, 403, "Sicherheits-Token abgelaufen",
            "Lade die Seite neu und versuche es erneut.")

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

    def require_verified_user(request: Request) -> RedirectResponse | None:
        if (redirect := require_user(request)) is not None:
            return redirect
        if request.session.get("role") == "owner":
            return None
        if not request.session.get("email_verified"):
            return RedirectResponse("/verify-pending", status_code=303)
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

    def _active_profile(request: Request):
        """(profile, None) für das aktive Profil der Session. (None, redirect) wenn
        nicht eingeloggt/unverifiziert; (None, None) wenn eingeloggt, aber ohne
        Profil — Seiten zeigen dann den Leer-Zustand mit Profil-anlegen-CTA."""
        if (redirect := require_verified_user(request)) is not None:
            return None, redirect
        profiles = storage.list_profiles(active_only=True,
                                         user_id=request.session.get("user_id"))
        if not profiles:
            return None, None
        pid = request.session.get("active_profile_id")
        profile = next((p for p in profiles if p["id"] == pid), None)
        if profile is None:
            profile = next((p for p in profiles if p["is_default"]), profiles[0])
            request.session["active_profile_id"] = profile["id"]
        return profile, None

    def _nav_profiles(request: Request) -> list[dict]:
        """Profil-Liste für den Topbar-Switcher (leer wenn ausgeloggt)."""
        uid = request.session.get("user_id")
        if uid is None:
            return []
        return storage.list_profiles(active_only=True, user_id=uid)
    templates.env.globals["nav_profiles"] = _nav_profiles

    def _unread_count(request: Request) -> int:
        uid = request.session.get("user_id")
        return storage.count_unread(uid) if uid is not None else 0
    templates.env.globals["unread_count"] = _unread_count

    def _relzeit(ts) -> str:
        if not ts:
            return "noch nie"
        delta = max(0, int(time.time()) - int(ts))
        if delta < 90:
            return "gerade eben"
        if delta < 3600:
            return f"vor {delta // 60} Min."
        if delta < 86400:
            return f"vor {delta // 3600} Std."
        return f"vor {delta // 86400} Tg."
    templates.env.filters["relzeit"] = _relzeit
    templates.env.filters["relzeit_datum"] = relzeit_datum

    def _may_manage_portal(request: Request, portal: dict) -> bool:
        """True wenn der eingeloggte User Ersteller des Portals ODER Site-Admin ist."""
        return (portal["submitted_by"] == request.session.get("user_id")
                or request.session.get("role") == "owner")

    @app.get("/login")
    def login_form(request: Request):
        return templates.TemplateResponse(request, "login.html", {"error": None})

    @app.post("/login")
    def login_submit(request: Request, email: str = Form(...), password: str = Form(...),
                     csrf_token: str = Form("")):
        if not csrf.verify(request, csrf_token):
            return _csrf_error_page(request)
        ip = client_ip(request)
        if not app.state.rate_limiter.hit(f"login:{ip}"):
            return templates.TemplateResponse(
                request, "login.html", {"error": "Zu viele Versuche — bitte später erneut"},
                status_code=429)
        user = storage.verify_password(email, password)
        if user is not None:
            request.session["user_id"] = user["id"]
            request.session["email"] = user["email"]
            request.session["role"] = user["role"]
            request.session["email_verified"] = user["email_verified_at"] is not None
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

    @app.get("/anleitung")
    def anleitung_view(request: Request):
        return RedirectResponse("/hilfe#anleitung", status_code=301)

    @app.get("/anleitung/keys")
    def anleitung_keys_view(request: Request):
        return templates.TemplateResponse(request, "keys.html", {})

    @app.get("/anleitung/scan")
    def anleitung_scan_view(request: Request):
        return templates.TemplateResponse(request, "anleitung_scan.html", {})

    @app.get("/hilfe")
    def hilfe_view(request: Request):
        return templates.TemplateResponse(request, "hilfe.html", {})

    @app.get("/onboarding")
    def onboarding_view(request: Request):
        return RedirectResponse("/hilfe#erste-schritte", status_code=301)

    @app.get("/account/passwort")
    def account_password_form(request: Request):
        if (redirect := require_user(request)) is not None:
            return redirect
        return RedirectResponse("/einstellungen", status_code=303)

    def _settings_extra(user_id):
        """Context-Keys, die settings.html auf jedem Render braucht."""
        user = storage.get_user(user_id)
        own = storage.list_profiles(user_id=user_id)
        spar = storage.get_spar_modus(own[0]["data"]) if own else dict(storage.SPAR_MODUS_DEFAULT)
        notify_pref = storage.get_notify_pref(own[0]["data"]) if own else dict(storage.NOTIFY_PREF_DEFAULT)
        return {"has_claude_kit": bool(user.get("api_token_hash")), "spar_modus": spar,
                "notify_pref": notify_pref,
                "has_firecrawl_key": bool(storage.get_firecrawl_key_enc(user_id)),
                "scan_portals": (storage.get_scan_portals(own[0]["data"], user_id) if own
                                 else list(storage.SCAN_PORTALS_DEFAULT)),
                "custom_scan_portals": [
                    {"id": cp["id"], "domain": urlparse(cp["url"]).netloc or cp["url"]}
                    for cp in storage.list_scannable_custom_portals(owner_id=user_id)]}

    @app.post("/account/passwort")
    def account_password_submit(
        request: Request,
        current_password: str = Form(...),
        new_password: str = Form(...),
        new_password_repeat: str = Form(...),
        csrf_token: str = Form(""),
    ):
        if (redirect := require_user(request)) is not None:
            return redirect
        if not csrf.verify(request, csrf_token):
            return _csrf_error_page(request)
        email = request.session.get("email")

        def _err(msg):
            return templates.TemplateResponse(
                request, "settings.html",
                {"error": msg, "success": None, "api_token": None,
                 "active_tab": "profil",
                 **_settings_extra(request.session["user_id"])}, status_code=400)

        if storage.verify_password(email, current_password) is None:
            return _err("Aktuelles Passwort ist falsch")
        if new_password != new_password_repeat:
            return _err("Passwörter stimmen nicht überein")
        if len(new_password) < 6:
            return _err("Neues Passwort muss mindestens 6 Zeichen haben")
        storage.set_password(request.session.get("user_id"), new_password)
        return templates.TemplateResponse(
            request, "settings.html",
            {"error": None, "success": "Passwort geändert", "api_token": None,
             "active_tab": "profil",
             **_settings_extra(request.session["user_id"])})

    @app.get("/account/email")
    def account_email_form(request: Request):
        if (redirect := require_user(request)) is not None:
            return redirect
        return templates.TemplateResponse(request, "account_email.html",
                                          {"error": None, "success": None})

    @app.post("/account/email")
    def account_email_submit(request: Request, new_email: str = Form(...),
                             csrf_token: str = Form("")):
        if (redirect := require_user(request)) is not None:
            return redirect
        if not csrf.verify(request, csrf_token):
            return _csrf_error_page(request)
        token = storage.request_email_change(request.session["user_id"], new_email)
        if token is None:
            return templates.TemplateResponse(request, "account_email.html",
                {"error": "Email bereits vergeben", "success": None}, status_code=409)
        try:
            mailer.send_email_change_verification(
                new_email.strip().lower(), token, settings["base_url"])
        except Exception:
            pass
        return templates.TemplateResponse(request, "account_email.html",
            {"error": None, "success": "Bestätigungs-Mail an neue Adresse gesendet"})

    @app.get("/account/email/confirm")
    def account_email_confirm(request: Request, token: str = ""):
        if (redirect := require_user(request)) is not None:
            return redirect
        user = storage.confirm_email_change(token)
        if user is None:
            return templates.TemplateResponse(request, "account_email.html",
                {"error": "Link ungültig", "success": None}, status_code=400)
        request.session["email"] = user["email"]
        request.session["email_verified"] = True
        return templates.TemplateResponse(request, "account_email.html",
            {"error": None, "success": "Email geändert"})

    @app.get("/account/export")
    def account_export(request: Request):
        if (redirect := require_user(request)) is not None:
            return redirect
        data = storage.export_user_data(request.session["user_id"])
        return JSONResponse(data, headers={
            "Content-Disposition": "attachment; filename=meine-daten.json"})

    @app.post("/account/loeschen")
    def account_delete(request: Request, current_password: str = Form(...),
                       csrf_token: str = Form("")):
        if (redirect := require_user(request)) is not None:
            return redirect
        if not csrf.verify(request, csrf_token):
            return _csrf_error_page(request)
        email = request.session.get("email")
        if storage.verify_password(email, current_password) is None:
            return templates.TemplateResponse(request, "account_email.html",
                {"error": "Passwort ist falsch", "success": None}, status_code=400)
        storage.delete_user(request.session["user_id"])
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    @app.get("/einstellungen")
    def settings_view(request: Request, tab: str = "profil"):
        if (redirect := require_user(request)) is not None:
            return redirect
        return templates.TemplateResponse(request, "settings.html", {
            "error": None, "success": None, "api_token": None,
            "active_tab": tab if tab in ("profil", "token", "notify", "firecrawl") else "profil",
            **_settings_extra(request.session["user_id"])})

    @app.get("/benachrichtigungen")
    def notifications_view(request: Request):
        if (redirect := require_user(request)) is not None:
            return redirect
        uid = request.session["user_id"]
        rows = storage.list_inbox(uid)          # aktueller Lesezustand (● vor Markierung)
        storage.mark_inbox_read(uid)            # danach alles gelesen → Badge auf 0
        return templates.TemplateResponse(request, "benachrichtigungen.html", {"rows": rows})

    @app.post("/einstellungen/spar-modus")
    def spar_modus_submit(request: Request, modus: str = Form("unbegrenzt"),
                          max_jobs: int = Form(25), neighbor_roles: str = Form(None),
                          locations: str = Form(""), lang_de: str = Form(None),
                          lang_en: str = Form(None), csrf_token: str = Form("")):
        if (redirect := require_user(request)) is not None:
            return redirect
        if not csrf.verify(request, csrf_token):
            return JSONResponse({"error": "csrf"}, status_code=403)
        limit = max(1, min(int(max_jobs), 500)) if modus == "sparsam" else None
        locs = [s.strip() for s in locations.split(",") if s.strip()]
        langs = [l for l, on in (("de", lang_de), ("en", lang_en)) if on is not None] or ["de"]
        storage.set_spar_modus(request.session["user_id"], limit,
                               neighbor_roles is not None, locs, langs)
        return RedirectResponse("/einstellungen?tab=token", status_code=303)

    @app.post("/einstellungen/scan-portale")
    async def scan_portals_submit(request: Request):
        if (redirect := require_user(request)) is not None:
            return redirect
        form = await request.form()
        if not csrf.verify(request, form.get("csrf_token", "")):
            return JSONResponse({"error": "csrf"}, status_code=403)
        portals = [name for name in ("stepstone", "indeed")
                   if f"portal_{name}" in form]
        portals += [f"custom:{key.removeprefix('portal_custom_')}"
                    for key in form
                    if key.startswith("portal_custom_")
                    and key.removeprefix("portal_custom_").isdigit()]
        storage.set_scan_portals(request.session["user_id"], portals)
        return RedirectResponse("/einstellungen?tab=token", status_code=303)

    @app.post("/einstellungen/notify")
    def notify_submit(request: Request, email_mode: str = Form("daily"),
                      immediate: str = Form(None), inbox: str = Form(None),
                      csrf_token: str = Form("")):
        if (redirect := require_user(request)) is not None:
            return redirect
        if not csrf.verify(request, csrf_token):
            return JSONResponse({"error": "csrf"}, status_code=403)
        pref = {"email_mode": email_mode if email_mode in ("daily", "weekly", "off") else "daily",
                "immediate": immediate is not None,
                "inbox": inbox is not None}
        storage.set_notify_pref(request.session["user_id"], pref)
        return RedirectResponse("/einstellungen?tab=notify", status_code=303)

    @app.post("/einstellungen/firecrawl")
    def firecrawl_key_submit(request: Request, firecrawl_key: str = Form(""),
                             csrf_token: str = Form("")):
        if (redirect := require_user(request)) is not None:
            return redirect
        if not csrf.verify(request, csrf_token):
            return _csrf_error_page(request)
        uid = request.session["user_id"]
        key = firecrawl_key.strip()
        if not key or not browser.validate_firecrawl_key(key):
            return templates.TemplateResponse(request, "settings.html", {
                "error": "Firecrawl-Key ungültig oder ohne Kontingent — abgelehnt.",
                "success": None, "api_token": None, "active_tab": "firecrawl",
                **_settings_extra(uid)})
        storage.set_firecrawl_key(uid, crypto.encrypt(key))
        return RedirectResponse("/einstellungen?tab=firecrawl", status_code=303)

    @app.post("/einstellungen/firecrawl/loeschen")
    def firecrawl_key_delete(request: Request, csrf_token: str = Form("")):
        if (redirect := require_user(request)) is not None:
            return redirect
        if not csrf.verify(request, csrf_token):
            return _csrf_error_page(request)
        storage.clear_firecrawl_key(request.session["user_id"])
        return RedirectResponse("/einstellungen?tab=firecrawl", status_code=303)

    @app.get("/register")
    def register_form(request: Request):
        return templates.TemplateResponse(request, "register.html", {"error": None})

    @app.post("/register")
    def register_submit(request: Request, email: str = Form(...),
                        password: str = Form(...), invite_code: str = Form(...),
                        consent: str = Form(None), csrf_token: str = Form("")):
        if not csrf.verify(request, csrf_token):
            return _csrf_error_page(request)
        ip = client_ip(request)
        if not app.state.rate_limiter.hit(f"register:{ip}"):
            return templates.TemplateResponse(
                request, "register.html", {"error": "Zu viele Versuche — bitte später erneut"},
                status_code=429)
        if not settings["invite_code"] or not hmac.compare_digest(
                invite_code, settings["invite_code"]):
            return templates.TemplateResponse(
                request, "register.html", {"error": "Ungültiger Invite-Code"}, status_code=403)
        if consent is None:
            return templates.TemplateResponse(
                request, "register.html",
                {"error": "Bitte Datenschutzerklärung akzeptieren"}, status_code=400)
        email = email.strip().lower()
        if storage.get_user_by_email(email) is not None:
            return templates.TemplateResponse(
                request, "register.html", {"error": "Email bereits registriert"}, status_code=409)
        uid = storage.create_user(email, password, role="member", consent=True, ip=ip)
        user = storage.get_user(uid)
        try:
            mailer.send_verification_email(email, user["verify_token"], settings["base_url"])
        except Exception:
            pass
        request.session["user_id"] = uid
        request.session["email"] = email
        request.session["role"] = "member"
        request.session["email_verified"] = False
        return RedirectResponse("/", status_code=303)

    @app.get("/forgot-password")
    def forgot_password_form(request: Request):
        return templates.TemplateResponse(request, "forgot_password.html", {"sent": False})

    @app.post("/forgot-password")
    def forgot_password_submit(request: Request, email: str = Form(...),
                               csrf_token: str = Form("")):
        if not csrf.verify(request, csrf_token):
            return _csrf_error_page(request)
        token = storage.create_reset_token(email)
        if token:
            try:
                mailer.send_password_reset_email(
                    email.strip().lower(), token, settings["base_url"])
            except Exception:
                pass
        return templates.TemplateResponse(request, "forgot_password.html", {"sent": True})

    @app.get("/reset-password")
    def reset_password_form(request: Request, token: str = ""):
        if storage.get_user_by_reset_token(token) is None:
            return templates.TemplateResponse(
                request, "reset_password.html",
                {"token": "", "error": "Link ungültig oder abgelaufen", "done": False},
                status_code=400)
        return templates.TemplateResponse(
            request, "reset_password.html", {"token": token, "error": None, "done": False})

    @app.post("/reset-password")
    def reset_password_submit(request: Request, token: str = Form(""),
                              new_password: str = Form(...),
                              new_password_repeat: str = Form(...),
                              csrf_token: str = Form("")):
        if not csrf.verify(request, csrf_token):
            return _csrf_error_page(request)

        def _err(msg):
            return templates.TemplateResponse(
                request, "reset_password.html",
                {"token": token, "error": msg, "done": False}, status_code=400)

        user = storage.get_user_by_reset_token(token)
        if user is None:
            return _err("Link ungültig oder abgelaufen")
        if new_password != new_password_repeat:
            return _err("Passwörter stimmen nicht überein")
        if len(new_password) < 6:
            return _err("Passwort muss mindestens 6 Zeichen haben")
        storage.set_password(user["id"], new_password)
        storage.clear_reset_token(user["id"])
        return templates.TemplateResponse(
            request, "reset_password.html", {"token": "", "error": None, "done": True})

    @app.get("/verify-pending")
    def verify_pending_view(request: Request, sent: str = "", cooldown: str = "", error: str = ""):
        if (redirect := require_user(request)) is not None:
            return redirect
        return templates.TemplateResponse(request, "verify_pending.html", {
            "sent": sent == "1", "cooldown": cooldown == "1", "error": error == "1"})

    @app.post("/verify-email/resend")
    def verify_email_resend(request: Request, csrf_token: str = Form("")):
        if (redirect := require_user(request)) is not None:
            return redirect
        if not csrf.verify(request, csrf_token):
            return _csrf_error_page(request)
        if request.session.get("email_verified"):
            return RedirectResponse("/", status_code=303)
        user = storage.get_user(request.session["user_id"])
        if user is None:
            return RedirectResponse("/verify-pending", status_code=303)
        if not app.state.resend_rate_limiter.hit(f"resend:{user['id']}"):
            return RedirectResponse("/verify-pending?cooldown=1", status_code=303)
        token = storage.ensure_verify_token(user["id"])
        if not token:
            return RedirectResponse("/verify-pending?error=1", status_code=303)
        try:
            mailer.send_verification_email(user["email"], token, settings["base_url"])
        except Exception:
            return RedirectResponse("/verify-pending?error=1", status_code=303)
        return RedirectResponse("/verify-pending?sent=1", status_code=303)

    @app.get("/verify-email")
    def verify_email_view(request: Request, token: str = ""):
        user = storage.verify_token_owner(token)
        if user is None:
            return _error_page(
                request, 404, "Verifizierungs-Link ungültig oder abgelaufen",
                "Fordere in den Kontoeinstellungen eine neue Verify-Mail an.")
        storage.mark_email_verified(user["id"])
        if request.session.get("user_id") == user["id"]:
            request.session["email_verified"] = True
        return RedirectResponse("/login", status_code=303)

    @app.get("/")
    def home_view(request: Request):
        if request.session.get("user_id") is None:
            return templates.TemplateResponse(request, "profiles.html", {})
        profile, resp = _active_profile(request)
        if resp is not None:
            return resp
        summary = storage.get_home_summary(profile["id"]) if profile else None
        steps = {
            "profil": profile is not None,
            "scan": bool(summary and summary["last_scan_ts"]),
            "votes": bool(summary and summary["vote_count"] >= 5),
        }
        ctx = {
            "profile": profile,
            "summary": summary,
            "steps": steps,
            "steps_done": all(steps.values()),
        }
        if profile is not None:
            pid = profile["id"]
            ctx.update({
                "feedback": storage.get_feedback_map(pid),
                "favorites": storage.get_favorites_set(pid),
                "criteria": storage.list_criteria(pid),
            })
        return templates.TemplateResponse(request, "home.html", ctx)

    @app.post("/profiles/{profile_id}/delete")
    def delete_profile_route(request: Request, profile_id: int, csrf_token: str = Form("")):
        _profile, resp = _require_owned(request, profile_id)
        if resp is not None:
            return resp
        if not csrf.verify(request, csrf_token):
            return _csrf_error_page(request)
        storage.delete_profile(profile_id)
        if request.session.get("active_profile_id") == profile_id:
            request.session.pop("active_profile_id", None)
        return RedirectResponse("/profil", status_code=303)

    @app.post("/profiles/api-token")
    def create_api_token_route(request: Request, csrf_token: str = Form("")):
        if (redirect := require_user(request)) is not None:
            return redirect
        if not csrf.verify(request, csrf_token):
            return _csrf_error_page(request)
        token = storage.create_api_token(request.session["user_id"])
        return templates.TemplateResponse(request, "settings.html", {
            "error": None, "success": None, "api_token": token,
            "active_tab": "token",
            **_settings_extra(request.session["user_id"])})

    @app.post("/profil/aktiv")
    def set_active_profile(request: Request, profile_id: int = Form(...),
                           csrf_token: str = Form("")):
        profile, resp = _require_owned(request, profile_id)
        if resp is not None:
            return resp
        if not csrf.verify(request, csrf_token):
            return _csrf_error_page(request)
        request.session["active_profile_id"] = profile["id"]
        ref_path = urlparse(request.headers.get("referer") or "").path or "/"
        return RedirectResponse(ref_path, status_code=303)

    @app.get("/portale")
    def portale_view(request: Request):
        if (redirect := require_user(request)) is not None:
            return redirect
        portale = storage.list_custom_portals()
        for p in portale:
            p["can_manage"] = _may_manage_portal(request, p)
        return templates.TemplateResponse(request, "portale.html", {
            "portale": portale, "is_owner": request.session.get("role") == "owner",
            "has_firecrawl_key": bool(storage.get_firecrawl_key_enc(request.session["user_id"])),
            "result": None})

    @app.post("/portale/pruefen")
    def portale_pruefen(request: Request, url: str = Form(...), typ: str = Form(...),
                        search_url_template: str = Form(""), detail_url_pattern: str = Form(""),
                        is_global: bool = Form(False), csrf_token: str = Form("")):
        if (redirect := require_user(request)) is not None:
            return redirect
        if not csrf.verify(request, csrf_token):
            return _csrf_error_page(request)
        allow_global = is_global and request.session.get("role") == "owner"
        pid = storage.create_custom_portal(
            url, typ, request.session["user_id"],
            search_url_template=search_url_template or None,
            detail_url_pattern=detail_url_pattern or None,
            is_global=allow_global)
        result = precheck.precheck_portal(url)
        storage.save_check_result(pid, result)
        portale = storage.list_custom_portals()
        for p in portale:
            p["can_manage"] = _may_manage_portal(request, p)
        return templates.TemplateResponse(request, "portale.html", {
            "portale": portale,
            "is_owner": request.session.get("role") == "owner",
            "has_firecrawl_key": bool(storage.get_firecrawl_key_enc(request.session["user_id"])),
            "result": storage.get_custom_portal(pid)})

    @app.post("/portale/pruefen-firecrawl/{portal_id}")
    def portale_pruefen_firecrawl(request: Request, portal_id: int,
                                  csrf_token: str = Form("")):
        if (redirect := require_user(request)) is not None:
            return redirect
        if not csrf.verify(request, csrf_token):
            return _csrf_error_page(request)
        portal = storage.get_custom_portal(portal_id)
        if portal is None or not _may_manage_portal(request, portal):
            return RedirectResponse("/portale", status_code=303)
        enc = storage.get_firecrawl_key_enc(request.session["user_id"])
        key = crypto.decrypt(enc) if enc else None
        if not key:
            return RedirectResponse("/einstellungen?tab=firecrawl", status_code=303)
        result = precheck.precheck_portal(portal["url"], use_firecrawl=True, firecrawl_key=key)
        storage.save_check_result(portal_id, result)
        if result.get("compatible"):
            storage.set_firecrawl_failover(portal_id, True)
        portale = storage.list_custom_portals()
        for p in portale:
            p["can_manage"] = _may_manage_portal(request, p)
        return templates.TemplateResponse(request, "portale.html", {
            "portale": portale,
            "is_owner": request.session.get("role") == "owner",
            "has_firecrawl_key": True,
            "result": storage.get_custom_portal(portal_id)})

    @app.post("/portale/aktivieren/{portal_id}")
    def portale_aktivieren(request: Request, portal_id: int, csrf_token: str = Form("")):
        if (redirect := require_user(request)) is not None:
            return redirect
        if not csrf.verify(request, csrf_token):
            return _csrf_error_page(request)
        portal = storage.get_custom_portal(portal_id)
        if portal is None:
            return RedirectResponse("/portale", status_code=303)
        if not _may_manage_portal(request, portal):
            return JSONResponse({"error": "forbidden"}, status_code=403)
        storage.activate_custom_portal(portal_id)
        return RedirectResponse("/portale", status_code=303)

    @app.post("/portale/deaktivieren/{portal_id}")
    def portale_deaktivieren(request: Request, portal_id: int, csrf_token: str = Form("")):
        if (redirect := require_user(request)) is not None:
            return redirect
        if not csrf.verify(request, csrf_token):
            return _csrf_error_page(request)
        portal = storage.get_custom_portal(portal_id)
        if portal is None:
            return RedirectResponse("/portale", status_code=303)
        if not _may_manage_portal(request, portal):
            return JSONResponse({"error": "forbidden"}, status_code=403)
        storage.deactivate_custom_portal(portal_id)
        return RedirectResponse("/portale", status_code=303)

    @app.post("/portale/loeschen/{portal_id}")
    def portale_loeschen(request: Request, portal_id: int, csrf_token: str = Form("")):
        if (redirect := require_user(request)) is not None:
            return redirect
        if not csrf.verify(request, csrf_token):
            return _csrf_error_page(request)
        portal = storage.get_custom_portal(portal_id)
        if portal is None:
            return RedirectResponse("/portale", status_code=303)
        if not _may_manage_portal(request, portal):
            return JSONResponse({"error": "forbidden"}, status_code=403)
        storage.soft_delete_custom_portal(portal_id)
        return RedirectResponse("/portale", status_code=303)

    _DASHBOARD_TABS = ("aktiv", "no_go", "bewertet", "ausland", "wartet")
    _DASHBOARD_PAGE_SIZE = 25
    _FUNNEL_STEPS = (("onboarding_start", "Onboarding-Start"),
                     ("profil_erstellt", "Profil erstellt"),
                     ("feedback_gegeben", "Feedback gegeben"))
    _WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]

    @app.get("/dashboard/{profile_id}")
    def dashboard_redirect(request: Request, profile_id: int, tab: str = ""):
        """301 auf die neuen flachen Seiten — Bookmarks und Tour-Anker bleiben gültig.
        Eigenes Profil in der URL wird als aktives Profil übernommen (best effort)."""
        profile = storage.get_profile(profile_id)
        if (profile is not None
                and profile.get("user_id") == request.session.get("user_id")):
            request.session["active_profile_id"] = profile_id
        target = (f"/jobs?tab={tab}" if tab in _DASHBOARD_TABS else "/jobs")
        return RedirectResponse(target, status_code=301)

    @app.get("/dashboard/{profile_id}/metriken")
    def metrics_redirect(request: Request, profile_id: int):
        return RedirectResponse("/metriken", status_code=301)

    @app.get("/jobs")
    def jobs_view(request: Request, tab: str = "aktiv",
                  page: int | None = None, q: str = "",
                  sort: str = "score", min_score: int = 0):
        profile, resp = _active_profile(request)
        if resp is not None:
            return resp
        if profile is None:
            return RedirectResponse("/", status_code=303)
        profile_id = profile["id"]
        if tab not in _DASHBOARD_TABS:
            tab = "aktiv"
        feedback = storage.get_feedback_map(profile_id)
        favorites = storage.get_favorites_set(profile_id)
        spar = profile["data"].get("spar_modus") or {}
        aktiv, no_go, bewertet, ausland, wartet = [], [], [], [], []
        for entry in storage.list_jobs_with_scores(profile_id,
                                                    locations=spar.get("locations"),
                                                    languages=spar.get("languages")):
            fp = entry["job"].fingerprint
            if entry["score"] is None:
                wartet.append(entry)
            elif feedback.get(fp) == "down":
                bewertet.append(entry)
            elif entry["is_ausland"]:
                ausland.append(entry)
            elif entry["category"] == "No-Go":
                no_go.append(entry)
            else:
                aktiv.append(entry)
        entries_by_tab = {"aktiv": aktiv, "no_go": no_go,
                          "bewertet": bewertet, "ausland": ausland,
                          "wartet": wartet}
        tab_entries = entries_by_tab[tab]
        if tab == "aktiv":
            if min_score > 0:
                tab_entries = [e for e in tab_entries
                               if (e["score"] or 0) >= min_score]
            if sort == "neu":
                # Stabiler Sort erhält den SQL-Tiebreak (first_seen DESC, id DESC)
                tab_entries = sorted(tab_entries,
                                     key=lambda e: e["job"].first_seen, reverse=True)
            elif sort == "gescored":
                tab_entries = sorted(tab_entries,
                                     key=lambda e: e["scored_at"] or "", reverse=True)
            elif sort == "kombi":
                cutoff = (date.today() - timedelta(days=7)).isoformat()
                fresh = [e for e in tab_entries if e["job"].first_seen >= cutoff]
                old = [e for e in tab_entries if e["job"].first_seen < cutoff]
                tab_entries = fresh + old
            # sort == "score": Master-Order (Score DESC) unverändert
        q_low = q.strip().lower()
        if q_low:
            tab_entries = [
                e for e in tab_entries
                if q_low in (
                    (e["job"].title or "") + " " + (e["job"].company or "") + " "
                    + (e["job"].location or "") + " " + (e["reason"] or "")
                ).lower()
            ]
        result_count = len(tab_entries)
        dash_pages = request.session.get("dash_pages", {})
        if page is not None:
            persist = True
        elif q_low:
            page = 1
            persist = False
        else:
            page = dash_pages.get(tab, 1)
            persist = True
        total_pages = max(1, (len(tab_entries) + _DASHBOARD_PAGE_SIZE - 1)
                          // _DASHBOARD_PAGE_SIZE)
        page = max(1, min(page, total_pages))
        if persist:
            dash_pages[tab] = page
            request.session["dash_pages"] = dash_pages
        start = (page - 1) * _DASHBOARD_PAGE_SIZE
        entries = tab_entries[start:start + _DASHBOARD_PAGE_SIZE]
        notify_count = len(storage.list_unnotified_top_matches(profile_id))
        if notify_count:
            storage.mark_notified(
                profile_id,
                [r["fingerprint"]
                 for r in storage.list_unnotified_top_matches(profile_id)])
        return templates.TemplateResponse(request, "jobs.html", {
            "profile": profile,
            "notify_count": notify_count,
            "criteria": storage.list_criteria(profile_id),
            "entries": entries,
            "feedback": feedback,
            "favorites": favorites,
            "tab": tab,
            "page": page,
            "total_pages": total_pages,
            "q": q,
            "sort": sort,
            "min_score": min_score,
            "wartet_count": len(wartet),
            "result_count": result_count,
            "counts": {"aktiv": len(aktiv), "no_go": len(no_go),
                       "bewertet": len(bewertet), "ausland": len(ausland)},
        })

    @app.get("/favoriten")
    def favoriten_view(request: Request):
        profile, resp = _active_profile(request)
        if resp is not None:
            return resp
        if profile is None:
            return RedirectResponse("/", status_code=303)
        pid = profile["id"]
        spar = profile["data"].get("spar_modus") or {}
        return templates.TemplateResponse(request, "favoriten.html", {
            "profile": profile,
            "fav_entries": storage.list_favorites_with_scores(
                pid, locations=spar.get("locations"), languages=spar.get("languages")),
            "feedback": storage.get_feedback_map(pid),
            "favorites": storage.get_favorites_set(pid),
            "criteria": storage.list_criteria(pid),
        })

    @app.get("/feintuning")
    def feintuning_view(request: Request):
        profile, resp = _active_profile(request)
        if resp is not None:
            return resp
        if profile is None:
            return RedirectResponse("/", status_code=303)
        return templates.TemplateResponse(request, "feintuning.html", {
            "profile": profile,
            "criteria": storage.list_criteria(profile["id"]),
        })

    @app.get("/lernen")
    def lernen_view(request: Request):
        profile, resp = _active_profile(request)
        if resp is not None:
            return resp
        if profile is None:
            return RedirectResponse("/", status_code=303)
        pid = profile["id"]
        feedback = storage.get_feedback_map(pid)
        return templates.TemplateResponse(request, "lernen.html", {
            "profile": profile,
            "analysis": storage.get_latest_analysis(pid),
            "proposed_insights": storage.list_insights(pid, status="proposed"),
            "active_insights": storage.list_insights(pid, status="confirmed"),
            "vote_count": len(feedback),
            "learn_reminder": storage.learn_reminder_status(pid),
        })

    @app.get("/scan")
    def scan_view(request: Request):
        profile, resp = _active_profile(request)
        if resp is not None:
            return resp
        summary = (storage.get_home_summary(profile["id"]) if profile
                   else {"last_scan_ts": None, "jobs_total": 0})
        return templates.TemplateResponse(request, "scan.html", {
            "last_scan_ts": summary["last_scan_ts"],
            "jobs_total": summary["jobs_total"],
        })

    @app.get("/profil")
    def profil_view(request: Request):
        if (redirect := require_verified_user(request)) is not None:
            return redirect
        return templates.TemplateResponse(request, "profil.html", {
            "profiles": storage.list_profiles(active_only=True,
                                              user_id=request.session.get("user_id")),
        })

    @app.get("/metriken")
    def metrics_view(request: Request):
        if (redirect := require_verified_user(request)) is not None:
            return redirect
        if (resp := require_owner(request)) is not None:
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
            "metrics": metrics,
            "feedback_rate": feedback_rate,
            "funnel_steps": funnel_steps,
            "daily_counts": daily_counts,
        })

    @app.post("/dashboard/{profile_id}/criteria")
    async def save_criteria_route(request: Request, profile_id: int):
        if (redirect := require_verified_user(request)) is not None:
            return redirect
        _profile, resp = _require_owned(request, profile_id)
        if resp is not None:
            return resp
        form = await request.form()
        if not csrf.verify(request, form.get("csrf_token")):
            return _csrf_error_page(request)
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
        return RedirectResponse("/feintuning", status_code=303)

    @app.post("/dashboard/{profile_id}/feedback/{fingerprint}")
    async def feedback_route(request: Request, profile_id: int, fingerprint: str):
        if (redirect := require_verified_user(request)) is not None:
            return redirect
        _profile, resp = _require_owned(request, profile_id)
        if resp is not None:
            return resp
        form = await request.form()
        if not csrf.verify(request, form.get("csrf_token")):
            return JSONResponse({"error": "csrf"}, status_code=403)
        vote = form.get("vote")
        if vote in ("up", "down"):
            storage.add_feedback(profile_id, fingerprint, vote)
            storage.log_event("feedback_gegeben", user_id=request.session.get("user_id"))
        else:
            vote = None
        if "application/json" in request.headers.get("accept", ""):
            return JSONResponse({"vote": vote, "fingerprint": fingerprint})
        return RedirectResponse("/jobs", status_code=303)

    @app.post("/dashboard/{profile_id}/favorite/{fingerprint}")
    async def favorite_route(request: Request, profile_id: int, fingerprint: str):
        if (redirect := require_verified_user(request)) is not None:
            return redirect
        _profile, resp = _require_owned(request, profile_id)
        if resp is not None:
            return resp
        form = await request.form()
        if not csrf.verify(request, form.get("csrf_token")):
            return JSONResponse({"error": "csrf"}, status_code=403)
        is_fav = storage.toggle_favorite(profile_id, fingerprint)
        storage.log_event("favorit_toggled", user_id=request.session.get("user_id"))
        if "application/json" in request.headers.get("accept", ""):
            return JSONResponse({"favorite": is_fav, "fingerprint": fingerprint})
        return RedirectResponse("/jobs", status_code=303)

    _FEEDBACK_CONFIRMATION = "Bob hat's notiert. Danke!"

    @app.post("/api/feedback")
    async def member_feedback_route(request: Request):
        if not csrf.verify(request, request.headers.get("x-csrf-token")):
            return JSONResponse({"error": "csrf"}, status_code=403)
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

    @app.get("/admin/registrations")
    def admin_registrations_view(request: Request):
        if (resp := require_owner(request)) is not None:
            return resp
        registrations = storage.list_registrations()
        for reg in registrations:
            ip = reg.get("registered_ip")
            reg["rate_limit_count"] = (
                app.state.rate_limiter.count(f"register:{ip}")
                + app.state.rate_limiter.count(f"login:{ip}")) if ip else 0
        return templates.TemplateResponse(request, "admin_registrations.html", {
            "registrations": registrations,
        })

    @app.get("/admin/members")
    def admin_members_view(request: Request):
        if (resp := require_owner(request)) is not None:
            return resp
        return templates.TemplateResponse(request, "admin_members.html", {
            "members": storage.admin_list_members(),
        })

    @app.post("/admin/members/{user_id}/verify")
    def admin_member_verify(request: Request, user_id: int, csrf_token: str = Form("")):
        if (resp := require_owner(request)) is not None:
            return resp
        if not csrf.verify(request, csrf_token):
            return _csrf_error_page(request)
        storage.mark_email_verified(user_id)
        return RedirectResponse("/admin/members", status_code=303)

    @app.post("/admin/members/{user_id}/resend-verify")
    def admin_member_resend(request: Request, user_id: int, csrf_token: str = Form("")):
        if (resp := require_owner(request)) is not None:
            return resp
        if not csrf.verify(request, csrf_token):
            return _csrf_error_page(request)
        user = storage.get_user(user_id)
        if user is not None:
            token = storage.ensure_verify_token(user_id)
            if token:
                try:
                    mailer.send_verification_email(user["email"], token, settings["base_url"])
                except Exception:
                    pass
        return RedirectResponse("/admin/members", status_code=303)

    @app.post("/admin/members/{user_id}/reset-password")
    def admin_member_reset(request: Request, user_id: int, csrf_token: str = Form("")):
        if (resp := require_owner(request)) is not None:
            return resp
        if not csrf.verify(request, csrf_token):
            return _csrf_error_page(request)
        user = storage.get_user(user_id)
        if user is not None:
            token = storage.create_reset_token(user["email"])
            if token:
                try:
                    mailer.send_password_reset_email(user["email"], token, settings["base_url"])
                except Exception:
                    pass
        return RedirectResponse("/admin/members", status_code=303)

    def _launch_feedback_agent(pass_name: str, analysis_id: int) -> None:
        try:
            subprocess.Popen(
                ["bash", "deploy/run_feedback_agent.sh", pass_name, str(analysis_id)],
                cwd=_REPO_ROOT,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

    @app.post("/dashboard/{profile_id}/analyze")
    def analyze_votes(request: Request, profile_id: int, csrf_token: str = Form("")):
        if (redirect := require_verified_user(request)) is not None:
            return redirect
        if (resp := require_owner(request)) is not None:
            return resp
        _profile, resp = _require_owned(request, profile_id)
        if resp is not None:
            return resp
        if not csrf.verify(request, csrf_token):
            return _csrf_error_page(request)
        analysis_id = storage.create_analysis(profile_id)
        _launch_feedback_agent("analyze", analysis_id)
        return RedirectResponse("/lernen", status_code=303)

    @app.get("/dashboard/{profile_id}/analysis")
    def analysis_status(request: Request, profile_id: int):
        if (redirect := require_verified_user(request)) is not None:
            return redirect
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
        if (redirect := require_verified_user(request)) is not None:
            return redirect
        if (resp := require_owner(request)) is not None:
            return resp
        _profile, resp = _require_owned(request, profile_id)
        if resp is not None:
            return resp
        if not csrf.verify(request, request.headers.get("x-csrf-token")):
            return JSONResponse({"error": "csrf"}, status_code=403)
        body = await request.json()
        storage.save_analysis_answers(body["analysis_id"], body.get("answers", {}), profile_id)
        return JSONResponse({"ok": True})

    @app.post("/dashboard/{profile_id}/finalize")
    def finalize_analysis(request: Request, profile_id: int, csrf_token: str = Form("")):
        if (redirect := require_verified_user(request)) is not None:
            return redirect
        if (resp := require_owner(request)) is not None:
            return resp
        _profile, resp = _require_owned(request, profile_id)
        if resp is not None:
            return resp
        if not csrf.verify(request, csrf_token):
            return _csrf_error_page(request)
        analysis = storage.get_latest_analysis(profile_id)
        if analysis is not None:
            storage.set_analysis_status(analysis["id"], "synthesizing")
            _launch_feedback_agent("synthesize", analysis["id"])
        return RedirectResponse("/lernen", status_code=303)

    @app.post("/dashboard/{profile_id}/insights/{insight_id}/confirm")
    def confirm_insight_route(request: Request, profile_id: int, insight_id: int,
                              csrf_token: str = Form("")):
        if (redirect := require_verified_user(request)) is not None:
            return redirect
        if (resp := require_owner(request)) is not None:
            return resp
        _profile, resp = _require_owned(request, profile_id)
        if resp is not None:
            return resp
        if not csrf.verify(request, csrf_token):
            return _csrf_error_page(request)
        storage.confirm_insight(insight_id, profile_id)
        return RedirectResponse("/lernen", status_code=303)

    @app.post("/dashboard/{profile_id}/insights/{insight_id}/reject")
    def reject_insight_route(request: Request, profile_id: int, insight_id: int,
                             csrf_token: str = Form("")):
        if (redirect := require_verified_user(request)) is not None:
            return redirect
        if (resp := require_owner(request)) is not None:
            return resp
        _profile, resp = _require_owned(request, profile_id)
        if resp is not None:
            return resp
        if not csrf.verify(request, csrf_token):
            return _csrf_error_page(request)
        storage.reject_insight(insight_id, profile_id)
        return RedirectResponse("/lernen", status_code=303)

    @app.post("/dashboard/{profile_id}/apply")
    def apply_insights(request: Request, profile_id: int, csrf_token: str = Form("")):
        if (redirect := require_verified_user(request)) is not None:
            return redirect
        if (resp := require_owner(request)) is not None:
            return resp
        _profile, resp = _require_owned(request, profile_id)
        if resp is not None:
            return resp
        if not csrf.verify(request, csrf_token):
            return _csrf_error_page(request)
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
        return RedirectResponse("/lernen", status_code=303)

    STEP_ORDER = ["basis", "skills", "zielrollen", "suchbegriffe", "domaenen",
                  "ort_umfang", "no_gos", "gewichte"]
    STEP_LABELS = {
        "basis": "Basics", "skills": "Skills", "zielrollen": "Zielrollen",
        "suchbegriffe": "Suchbegriffe", "domaenen": "Domänen",
        "ort_umfang": "Ort und Umfang",
        "no_gos": "No-Gos", "gewichte": "Gewichte",
    }

    def _split(text: str) -> list[str]:
        return [t.strip() for t in text.split(",") if t.strip()]

    def _wizard_state(request: Request) -> dict:
        return request.session.setdefault("wizard", {"data": {}, "suggestions": {}})

    @app.get("/wizard/new")
    def wizard_start(request: Request):
        if (redirect := require_verified_user(request)) is not None:
            return redirect
        request.session["wizard"] = {"data": {}, "suggestions": {}, "visited": []}
        storage.log_event("onboarding_start", user_id=request.session.get("user_id"))
        return RedirectResponse(f"/wizard/{STEP_ORDER[0]}", status_code=303)

    @app.get("/wizard/edit/{profile_id}")
    def wizard_edit(request: Request, profile_id: int):
        if (redirect := require_verified_user(request)) is not None:
            return redirect
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
            "visited": list(STEP_ORDER),
        }
        return RedirectResponse(f"/wizard/{STEP_ORDER[0]}", status_code=303)

    @app.get("/wizard/{step}")
    def wizard_step_form(request: Request, step: str):
        if (redirect := require_verified_user(request)) is not None:
            return redirect
        if step not in STEP_ORDER:
            return RedirectResponse("/wizard/new", status_code=303)
        wizard = _wizard_state(request)
        visited = wizard.setdefault("visited", [])
        if step not in visited:
            visited.append(step)
        request.session["wizard"] = wizard
        jumpable = list(STEP_ORDER) if wizard.get("edit_id") is not None else list(visited)
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
            "jumpable": jumpable,
        })

    @app.post("/wizard/llm-refine")
    async def wizard_llm_refine(request: Request):
        if (redirect := require_verified_user(request)) is not None:
            return redirect
        if (resp := require_owner(request)) is not None:
            return resp
        if (redirect := require_user(request)) is not None:
            return redirect
        form = await request.form()
        if not csrf.verify(request, form.get("csrf_token")):
            return JSONResponse({"error": "csrf"}, status_code=403)
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
        if (redirect := require_verified_user(request)) is not None:
            return redirect
        if step not in STEP_ORDER:
            return RedirectResponse("/wizard/new", status_code=303)
        form = await request.form()
        if not csrf.verify(request, form.get("csrf_token")):
            return _csrf_error_page(request)
        wizard = _wizard_state(request)
        data = wizard["data"]
        goto = form.get("goto")
        jumpable = (set(STEP_ORDER) if wizard.get("edit_id") is not None
                    else set(wizard.get("visited", [])))
        jumping = bool(goto) and goto in STEP_ORDER and goto in jumpable and goto != step
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
        elif step == "suchbegriffe":
            queries: dict[str, dict[str, list[str]]] = {}
            if not form.get("no_custom_queries"):
                for i, role in enumerate(data.get("target_roles", [])):
                    terms = [t.strip() for t in form.getlist(f"terms_{i}") if t.strip()]
                    if terms:
                        queries[role] = {"alle": terms}
            data["queries"] = queries
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
                nogos = set(_split(form.get("no_gos", "")))
                nogos.update(form.getlist("suggested_no_gos"))
                data["no_gos"] = sorted(nogos)
            else:
                valid = {n["key"] for n in scoring.NO_GOS_CATALOG}
                data["no_gos"] = [k for k in form.getlist("no_gos") if k in valid]
        elif step == "gewichte" and not jumping:
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
            queries = data.pop("queries", {})
            name = data.pop("name", "") or f"Profil {len(storage.list_profiles()) + 1}"
            edit_id = wizard.get("edit_id")
            if edit_id is not None:
                storage.update_profile(edit_id, name, data, queries=queries)
                storage.save_criteria(edit_id, criteria)
                pid = edit_id
            else:
                pid = storage.create_profile(name, data, queries=queries,
                                            user_id=request.session.get("user_id"))
                storage.save_criteria(pid, criteria)
                storage.log_event("profil_erstellt", user_id=request.session.get("user_id"))
            if role != "owner":
                storage.score_profile_deterministic(pid)
            request.session.pop("wizard", None)
            request.session["active_profile_id"] = pid
            return RedirectResponse("/", status_code=303)
        request.session["wizard"] = wizard
        if jumping:
            return RedirectResponse(f"/wizard/{goto}", status_code=303)
        next_step = STEP_ORDER[STEP_ORDER.index(step) + 1]
        return RedirectResponse(f"/wizard/{next_step}", status_code=303)

    async def _not_found_handler(request: Request, exc: StarletteHTTPException):
        if exc.status_code != 404:
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        if _wants_json(request):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        return _error_page(request, 404, "Seite nicht gefunden",
                           "Die Seite gibt es nicht (mehr).")

    async def _server_error_handler(request: Request, exc: Exception):
        if _wants_json(request):
            return JSONResponse({"detail": "Internal Server Error"}, status_code=500)
        return _error_page(request, 500, "Etwas ist schiefgelaufen",
                           "Ein interner Fehler ist aufgetreten. Bitte später erneut.",
                           home_only=True)

    app.add_exception_handler(StarletteHTTPException, _not_found_handler)
    app.add_exception_handler(Exception, _server_error_handler)

    return app
