"""A starter list of well-known companies with public job boards.

Slugs were correct when written, but companies migrate ATSes — verify with a
quick scan before relying on one (a wrong slug prints a one-line warning and
never breaks the rest of the scan).
"""

from __future__ import annotations

# (ats, slug, display name)
STARTER_COMPANIES: tuple[tuple[str, str, str], ...] = (
    ("greenhouse", "airbnb", "Airbnb"),
    ("greenhouse", "anthropic", "Anthropic"),
    ("greenhouse", "asana", "Asana"),
    ("greenhouse", "cloudflare", "Cloudflare"),
    ("greenhouse", "coinbase", "Coinbase"),
    ("greenhouse", "databricks", "Databricks"),
    ("greenhouse", "datadog", "Datadog"),
    ("greenhouse", "discord", "Discord"),
    ("greenhouse", "dropbox", "Dropbox"),
    ("greenhouse", "duolingo", "Duolingo"),
    ("greenhouse", "figma", "Figma"),
    ("greenhouse", "gitlab", "GitLab"),
    ("greenhouse", "lyft", "Lyft"),
    ("greenhouse", "mongodb", "MongoDB"),
    ("greenhouse", "pinterest", "Pinterest"),
    ("greenhouse", "reddit", "Reddit"),
    ("greenhouse", "robinhood", "Robinhood"),
    ("greenhouse", "roblox", "Roblox"),
    ("greenhouse", "stripe", "Stripe"),
    ("greenhouse", "twilio", "Twilio"),
    ("greenhouse", "vercel", "Vercel"),
    ("lever", "kraken", "Kraken"),
    ("lever", "palantir", "Palantir"),
    ("lever", "plaid", "Plaid"),
    ("lever", "wealthfront", "Wealthfront"),
    ("ashby", "cursor", "Cursor"),
    ("ashby", "deel", "Deel"),
    ("ashby", "linear", "Linear"),
    ("ashby", "notion", "Notion"),
    ("ashby", "openai", "OpenAI"),
    ("ashby", "posthog", "PostHog"),
    ("ashby", "ramp", "Ramp"),
    ("ashby", "replit", "Replit"),
    ("ashby", "zapier", "Zapier"),
)


def render() -> str:
    lines = [
        "Starter companies (copy the ats:slug entries you want into interninbox.toml):",
        "",
    ]
    width = max(len(f"{ats}:{slug}") for ats, slug, _ in STARTER_COMPANIES)
    for ats, slug, name in STARTER_COMPANIES:
        lines.append(f'  "{f"{ats}:{slug}"}"'.ljust(width + 6) + f"  # {name}")
    lines.append("")
    lines.append(
        "Note: companies migrate ATSes — verify a slug with a scan; a wrong one just "
        "prints a warning."
    )
    return "\n".join(lines)
