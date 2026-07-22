from starlette.requests import Request

from jobscanner.web import csrf


def _request(session=None):
    scope = {"type": "http", "session": session if session is not None else {}}
    return Request(scope)


def test_ensure_token_creates_and_persists_token_in_session():
    req = _request()
    token = csrf.ensure_token(req)
    assert token
    assert req.session["csrf_token"] == token


def test_ensure_token_is_idempotent():
    req = _request()
    first = csrf.ensure_token(req)
    second = csrf.ensure_token(req)
    assert first == second


def test_verify_accepts_matching_token():
    req = _request()
    token = csrf.ensure_token(req)
    assert csrf.verify(req, token) is True


def test_verify_rejects_mismatch_missing_or_no_session_token():
    req = _request()
    csrf.ensure_token(req)
    assert csrf.verify(req, "falsch") is False
    assert csrf.verify(req, None) is False
    assert csrf.verify(req, "") is False
    empty_req = _request()
    assert csrf.verify(empty_req, "irgendwas") is False
