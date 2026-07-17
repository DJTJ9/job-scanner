# tests/test_claude_llm.py
"""Tests für claude_llm.claude_json — subprocess.run gemockt, kein echter claude-Call."""
import subprocess
import types

import pytest

from jobscanner import claude_llm


def _fake_run(stdout):
    def run(argv, **kwargs):
        run.argv = argv
        run.kwargs = kwargs
        return types.SimpleNamespace(stdout=stdout, stderr="", returncode=0)
    return run


def test_claude_json_parses_clean_object(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run('{"skills": ["Python"]}'))
    assert claude_llm.claude_json("sys", "prompt") == {"skills": ["Python"]}


def test_claude_json_parses_clean_array(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run('[{"name": "x"}]'))
    assert claude_llm.claude_json("sys", "prompt") == [{"name": "x"}]


def test_claude_json_extracts_object_from_noisy_output(monkeypatch):
    monkeypatch.setattr(subprocess, "run",
                        _fake_run('Hier das JSON:\n{"a": 1}\nFertig.'))
    assert claude_llm.claude_json("sys", "prompt") == {"a": 1}


def test_claude_json_raises_on_unparseable(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run("kein json hier"))
    with pytest.raises(ValueError):
        claude_llm.claude_json("sys", "prompt")


def test_claude_json_invokes_absolute_binary_with_flags(monkeypatch):
    fake = _fake_run('{"ok": true}')
    monkeypatch.setattr(subprocess, "run", fake)
    claude_llm.claude_json("MEIN-SYSTEM", "MEIN-PROMPT", model="claude-haiku-4-5")
    argv = fake.argv
    assert argv[0] == "/root/.nvm/versions/node/v24.16.0/bin/claude"
    assert "-p" in argv and "MEIN-PROMPT" in argv
    assert argv[argv.index("--system-prompt") + 1] == "MEIN-SYSTEM"
    assert argv[argv.index("--model") + 1] == "claude-haiku-4-5"
    assert fake.kwargs["timeout"] == 60
