"""Gemeinsamer TestClient, der jeden POST automatisch mit einem gültigen
CSRF-Token versieht — spiegelt, was ein echter Browser durch das Meta-Tag
(base.html, gelesen von der Frontend-JS für Header) bzw. das versteckte
Formularfeld (_csrf_field.html) tut.

Hinweis: aktuell bindet noch kein Template `_csrf_field.html` ein (steht als
eigenständiger Partial für spätere Formulare bereit) — der einzige Ort, an dem
ein echtes Token für die aktuelle Session im gerenderten HTML auftaucht, ist
das Meta-Tag in base.html (`<meta name="csrf-token" content="...">`). Der
Helper liest deshalb von dort.
"""
import re

from fastapi.testclient import TestClient

_TOKEN_RE = re.compile(r'name="csrf-token" content="([^"]*)"')


class CSRFTestClient(TestClient):
    def _token(self) -> str:
        html = self.get("/login").text
        match = _TOKEN_RE.search(html)
        return match.group(1) if match else ""

    def post(self, url, **kwargs):
        if kwargs.get("json") is not None:
            headers = dict(kwargs.get("headers") or {})
            headers.setdefault("X-CSRF-Token", self._token())
            kwargs["headers"] = headers
        else:
            data = dict(kwargs.get("data") or {})
            data.setdefault("csrf_token", self._token())
            kwargs["data"] = data
        return super().post(url, **kwargs)
