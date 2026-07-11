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


def format_report(aggregate: dict, stats: dict | None = None) -> str:
    lines = ["📊 Markt-Report — Top-Skills"]
    for group, top in aggregate.items():
        lines.append(f"\n{group}:")
        for skill, count in top:
            lines.append(f"  {skill}: {count}")
    if stats and stats.get("neighbor_total", 0) > 0:
        lines.append(
            f"\n🔭 Nachbarfelder: {stats['neighbor_total']} Treffer "
            f"({stats['neighbor_pass']} Pass) zusätzlich zu "
            f"{stats['core_total']} Kern-Treffern ({stats['core_pass']} Pass)"
        )
    return "\n".join(lines)
