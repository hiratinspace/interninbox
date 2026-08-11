"""`interninbox companies` — the curated registry, human-readable."""

from __future__ import annotations

from interninbox.registry import REGISTRY


def render() -> str:
    lines = [
        "Curated companies (copy the ats:slug entries you want into interninbox.toml,",
        'or scan them all with `registry = "all"` / the wizard):',
        "",
    ]
    width = max(len(f'"{entry.ats}:{entry.slug}"') for entry in REGISTRY)
    for entry in sorted(REGISTRY, key=lambda e: (e.ats, e.slug)):
        label = f'"{entry.ats}:{entry.slug}"'.ljust(width)
        tags = ", ".join(entry.tags)
        lines.append(f"  {label}  # {entry.name}  [{entry.size}]  {tags}")
    lines.append("")
    lines.append(
        f"{len(REGISTRY)} companies, verified when authored — companies migrate ATSes, "
        "so verify a slug with a scan; a wrong one just prints a warning."
    )
    return "\n".join(lines)
