"""Pinnt die eingefrorene Deploy-Konfiguration: der Dienst liest aus dem Worktree, nicht aus dem Arbeits-Checkout."""
import os
from pathlib import Path

_DEPLOY = Path(__file__).resolve().parent.parent / "deploy"


def test_web_service_workingdirectory_is_frozen_deploy_dir():
    unit = (_DEPLOY / "jobscanner-web.service").read_text(encoding="utf-8")
    lines = [l for l in unit.splitlines() if l.startswith("WorkingDirectory=")]
    assert lines == ["WorkingDirectory=/opt/jobscanner-live"]


def test_deploy_web_script_checks_out_detached_and_restarts():
    script = (_DEPLOY / "deploy_web.sh").read_text(encoding="utf-8")
    assert "checkout --detach" in script
    assert "systemctl restart jobscanner-web.service" in script


def test_deploy_web_script_is_executable():
    assert os.access(_DEPLOY / "deploy_web.sh", os.X_OK)
