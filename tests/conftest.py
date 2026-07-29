"""Session-Defaults für Tests: Fernet-Key für den Boot-Assert in create_app()."""
import os

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

os.environ.setdefault("JOBSCANNER_FERNET_KEY", Fernet.generate_key().decode())

# Session-Cookie ist Secure (SessionMiddleware https_only=True) — beim http-Default
# "http://testserver" würde der Client das Cookie nicht zurücksenden. Zentral auf
# https heben statt alle Testclient-Aufrufe einzeln anzupassen.
_orig_testclient_init = TestClient.__init__


def _https_testclient_init(self, *args, **kwargs):
    kwargs.setdefault("base_url", "https://testserver")
    _orig_testclient_init(self, *args, **kwargs)


TestClient.__init__ = _https_testclient_init
