# jobscanner/claude_llm.py
"""Synchroner `claude -p`-Helper: System+Prompt → geparste JSON-Antwort (dict|list).

Ersetzt den Groq-Client an den zwei verbliebenen LLM-Call-Sites. Ruft das
claude-Binary per Absolutpfad (nvm-bin liegt nicht auf dem discover.service-PATH),
mit Haiku für Tempo/Kosten und ohne Tools (reine Text-Generierung). Wirft bei
Timeout (subprocess.TimeoutExpired) oder Parse-Fehler (ValueError) — die Aufrufer
behalten ihr bestehendes try/except."""
from __future__ import annotations

import json
import re
import subprocess

_CLAUDE_BIN = "/root/.nvm/versions/node/v24.16.0/bin/claude"
_DEFAULT_MODEL = "claude-haiku-4-5"


def _extract_json(text: str):
    """Fallback: ersten {…}- oder […]-Block aus verrauschter Ausgabe parsen.

    claude wickelt JSON gern in einen ```json-Codeblock. Bei einem Array greift das
    gierige `\\{.*\\}`-Muster dann fälschlich die inneren Objekte (→ "Extra data");
    darum wird ein Muster, dessen Treffer nicht als JSON parst, übersprungen statt
    den Fehler durchzureichen — das nächste Muster (`\\[.*\\]`) fängt das Array."""
    for pattern in (r"\{.*\}", r"\[.*\]"):
        match = re.search(pattern, text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                continue
    raise ValueError(f"Keine JSON-Struktur in claude-Ausgabe: {text[:200]!r}")


def claude_json(system: str, prompt: str,
                model: str = _DEFAULT_MODEL, timeout: int = 60):
    """Ruft `claude -p` und gibt die geparste JSON-Antwort zurück (dict oder list)."""
    result = subprocess.run(
        [_CLAUDE_BIN, "-p", prompt,
         "--system-prompt", system,
         "--model", model,
         "--allowedTools", "",
         "--output-format", "text"],
        capture_output=True, text=True, timeout=timeout,
        stdin=subprocess.DEVNULL,
    )
    out = (result.stdout or "").strip()
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return _extract_json(out)
