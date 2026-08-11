"""Named role presets — curated whole-word keyword sets for match_keywords.

Each preset narrows results to "internship AND (any of these words)" via the
existing match_keywords machinery. Keywords are whole-word matched, so they
must be specific: bare "engineer" would match every engineering discipline
and is deliberately absent. `interninbox roles` prints this table so nothing
is magic.
"""

from __future__ import annotations

ROLE_PRESETS: dict[str, tuple[str, ...]] = {
    "software": (
        "software", "swe", "developer", "backend", "back end", "frontend",
        "front end", "full stack", "fullstack", "platform", "mobile", "ios",
        "android", "devops", "sre", "site reliability", "computer science",
        "programming", "web",
    ),
    "data": (
        "data", "machine learning", "ml", "ai", "analytics", "data science",
        "business intelligence", "statistics", "quantitative", "quant",
    ),
    "cybersecurity": (
        "security", "cybersecurity", "cyber", "infosec", "information security",
        "threat", "soc", "appsec", "application security", "penetration",
        "pentest", "vulnerability", "grc", "incident response",
    ),
    "finance": (
        "finance", "financial", "accounting", "audit", "tax", "treasury",
        "investment", "banking", "equity research", "fp&a", "underwriting",
        "actuarial",
    ),
    "business": (
        "business", "management", "operations", "consulting", "strategy",
        "supply chain", "logistics", "procurement", "project management",
        "program management", "sales", "partnerships",
    ),
    "marketing": (
        "marketing", "growth", "brand", "communications", "social media",
        "content", "seo", "public relations",
    ),
    "design": (
        "design", "ux", "ui", "user experience", "product design",
        "graphic", "visual", "industrial design",
    ),
    "product": (
        "product", "product management", "apm", "technical program",
    ),
    "hardware": (
        "hardware", "electrical", "mechanical", "embedded", "firmware",
        "robotics", "manufacturing", "aerospace", "semiconductor", "asic",
        "fpga",
    ),
}


def expand_roles(names: tuple[str, ...]) -> tuple[str, ...]:
    """Union of the named presets' keywords, deduped, order-preserving.

    Raises ValueError naming the unknown role and the valid choices.
    """
    keywords: list[str] = []
    seen: set[str] = set()
    for name in names:
        key = name.strip().lower()
        if key not in ROLE_PRESETS:
            valid = ", ".join(sorted(ROLE_PRESETS))
            raise ValueError(f"unknown role {name!r} — valid roles: {valid}")
        for keyword in ROLE_PRESETS[key]:
            if keyword not in seen:
                seen.add(keyword)
                keywords.append(keyword)
    return tuple(keywords)


def render() -> str:
    lines = ["Role presets (use in [filters] roles = [...] or pick in the wizard):", ""]
    for name in sorted(ROLE_PRESETS):
        lines.append(f"  {name}")
        lines.append(f"      {', '.join(ROLE_PRESETS[name])}")
    lines.append("")
    lines.append("A role keeps only internships whose title contains one of its words "
                 "(whole-word).")
    return "\n".join(lines)
