"""Markt-Aggregation (4.2): Top-Skills/Tech-Stack über gespeicherte Jobs, optional je Zielrolle."""
from __future__ import annotations

from collections import Counter

from jobscanner.models import Job

TOP_N = 10


def aggregate_skills(jobs: list[Job], group_by_role: bool = False) -> dict:
    if not group_by_role:
        counter: Counter = Counter()
        for job in jobs:
            counter.update(job.requirements)
            counter.update(job.tech_stack)
        return {"gesamt": counter.most_common(TOP_N)}

    grouped: dict[str, Counter] = {}
    for job in jobs:
        key = job.role or "unbekannt"
        counter = grouped.setdefault(key, Counter())
        counter.update(job.requirements)
        counter.update(job.tech_stack)
    return {role: counter.most_common(TOP_N) for role, counter in grouped.items()}


def neighbor_stats(jobs: list[Job]) -> dict:
    core = [j for j in jobs if not j.is_neighbor]
    neighbor = [j for j in jobs if j.is_neighbor]
    return {
        "core_total": len(core),
        "core_pass": sum(1 for j in core if j.category == "Pass"),
        "neighbor_total": len(neighbor),
        "neighbor_pass": sum(1 for j in neighbor if j.category == "Pass"),
    }


def format_report(aggregate: dict, stats: dict | None = None,
                  new_jobs: list[Job] | None = None,
                  credits: dict | None = None) -> str:
    lines = []
    if new_jobs:
        scored = [j for j in new_jobs if j.score is not None and j.category != "No-Go"]
        top = sorted(scored, key=lambda j: j.score, reverse=True)[:5]
        if top:
            lines.append("🎯 Top-Treffer des Laufs:")
            for j in top:
                src = j.sources[0] if j.sources else {}
                lines.append(f"  {j.score} — {j.title} ({src.get('portal', '?')})")
                if src.get("url"):
                    lines.append(f"    {src['url']}")
        vetoes = [j for j in new_jobs if j.category == "No-Go"]
        if vetoes:
            lines.append("\n🚫 Vetos:")
            for j in vetoes[:5]:
                lines.append(f"  {j.title} — {j.score_reason}")
        if top or vetoes:
            lines.append("")
    lines.append("📊 Markt-Report — Top-Skills")
    for group, top_skills in aggregate.items():
        lines.append(f"\n{group}:")
        for skill, count in top_skills:
            lines.append(f"  {skill}: {count}")
    if stats and stats.get("neighbor_total", 0) > 0:
        lines.append(
            f"\n🔭 Nachbarfelder: {stats['neighbor_total']} Treffer "
            f"({stats['neighbor_pass']} Pass) zusätzlich zu "
            f"{stats['core_total']} Kern-Treffern ({stats['core_pass']} Pass)"
        )
    if credits is not None:
        real = credits.get("real")
        real_text = f"{real} echt" if real is not None else "echt: n/a"
        lines.append(f"\n💳 Firecrawl: ~{credits['estimated']} Credits geschätzt, "
                     f"{real_text} (Budget {credits['budget']})")
    return "\n".join(lines)
