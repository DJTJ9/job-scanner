"""Achse-2-Guard: Claude ist der einzige verdrahtete LLM — kein Nicht-Claude-Client-Import."""
import re
from pathlib import Path

_PKG = Path(__file__).resolve().parent.parent / "jobscanner"
_FORBIDDEN = ("groq", "openai", "mistralai", "cohere", "ollama",
              "google.generativeai", "genai")
_IMPORT_RE = re.compile(r"^\s*(?:import|from)\s+([\w.]+)")


def test_no_non_claude_llm_client_imported():
    offenders = []
    for py in _PKG.rglob("*.py"):
        for lineno, line in enumerate(py.read_text(encoding="utf-8").splitlines(), 1):
            m = _IMPORT_RE.match(line)
            if not m:
                continue
            mod = m.group(1)
            if any(mod == f or mod.startswith(f + ".") for f in _FORBIDDEN):
                offenders.append(f"{py.name}:{lineno}: {line.strip()}")
    assert not offenders, "Nicht-Claude-LLM-Import gefunden:\n" + "\n".join(offenders)
