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


def format_report(aggregate: dict) -> str:
    lines = ["📊 Markt-Report — Top-Skills"]
    for group, top in aggregate.items():
        lines.append(f"\n{group}:")
        for skill, count in top:
            lines.append(f"  {skill}: {count}")
    return "\n".join(lines)
