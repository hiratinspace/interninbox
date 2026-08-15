"""The curated company registry behind `--all` / the wizard's company menu.

Every entry was verified against its live public board API when authored
(scripts/verify_registry.py), slugs rot as companies migrate ATSes, so
re-verify when touching this file. A dead slug degrades gracefully at scan
time (one warning line), but shipping known-dead entries is not acceptable.
"""

from __future__ import annotations

from dataclasses import dataclass

TIERS: tuple[str, ...] = ("top", "all", "large", "startups")

# Very rough sequential-scan pacing: politeness floors same-host requests at
# 0.5 s and responses take a few hundred ms, so ~0.75 s per board.
_SECONDS_PER_BOARD = 0.75


@dataclass(frozen=True)
class RegistryCompany:
    ats: str
    slug: str
    name: str
    size: str  # "large" | "startup"
    tags: tuple[str, ...] = ()
    top: bool = False


def select(tier: str) -> tuple[RegistryCompany, ...]:
    if tier == "all":
        return REGISTRY
    if tier == "top":
        return tuple(entry for entry in REGISTRY if entry.top)
    if tier == "large":
        return tuple(entry for entry in REGISTRY if entry.size == "large")
    if tier == "startups":
        return tuple(entry for entry in REGISTRY if entry.size == "startup")
    valid = ", ".join(TIERS)
    raise ValueError(f"unknown registry tier {tier!r}; valid tiers: {valid}")


def estimate_label(count: int) -> str:
    """Human 'how long will this take' hint. Rough on purpose; network varies."""
    return _label(max(5, round(count * _SECONDS_PER_BOARD)))


def estimate_seconds(companies: object) -> int:
    """Request-weighted estimate: an enterprise SmartRecruiters board can take
    up to 10 paginated requests, not 1."""
    total = 0.0
    for company in companies:  # any object with an .ats attribute
        weight = 10 if getattr(company, "ats", "") == "smartrecruiters" else 1
        total += weight * _SECONDS_PER_BOARD
    return max(5, round(total))


def estimate_label_for(companies: object) -> str:
    return _label(estimate_seconds(companies))


def _label(seconds: int) -> str:
    if seconds < 90:
        return f"~{seconds} s"
    return f"~{max(2, round(seconds / 60))} min"


_G, _L, _A, _S = "greenhouse", "lever", "ashby", "smartrecruiters"
_W = "workable"

REGISTRY: tuple[RegistryCompany, ...] = (
    # ---- greenhouse, large ----
    RegistryCompany(_G, "stripe", "Stripe", "large", ("fintech",), top=True),
    RegistryCompany(_G, "airbnb", "Airbnb", "large", ("consumer",), top=True),
    RegistryCompany(_G, "coinbase", "Coinbase", "large", ("crypto",), top=True),
    RegistryCompany(_G, "databricks", "Databricks", "large", ("data",), top=True),
    RegistryCompany(_G, "datadog", "Datadog", "large", ("infra",), top=True),
    RegistryCompany(_G, "dropbox", "Dropbox", "large", ("productivity",), top=True),
    RegistryCompany(_G, "duolingo", "Duolingo", "large", ("consumer", "edtech"), top=True),
    RegistryCompany(_G, "figma", "Figma", "large", ("design",), top=True),
    RegistryCompany(_G, "gitlab", "GitLab", "large", ("devtools",), top=True),
    RegistryCompany(_G, "lyft", "Lyft", "large", ("consumer",), top=True),
    RegistryCompany(_G, "mongodb", "MongoDB", "large", ("data",), top=True),
    RegistryCompany(_G, "pinterest", "Pinterest", "large", ("consumer",), top=True),
    RegistryCompany(_G, "reddit", "Reddit", "large", ("consumer",), top=True),
    RegistryCompany(_G, "robinhood", "Robinhood", "large", ("fintech",), top=True),
    RegistryCompany(_G, "roblox", "Roblox", "large", ("gaming",), top=True),
    RegistryCompany(_G, "twilio", "Twilio", "large", ("infra",), top=True),
    RegistryCompany(_G, "cloudflare", "Cloudflare", "large", ("infra", "security"), top=True),
    RegistryCompany(_G, "anthropic", "Anthropic", "large", ("ai",), top=True),
    RegistryCompany(_G, "asana", "Asana", "large", ("productivity",)),
    RegistryCompany(_G, "discord", "Discord", "large", ("consumer", "gaming"), top=True),
    RegistryCompany(_G, "instacart", "Instacart", "large", ("consumer",), top=True),
    RegistryCompany(_G, "affirm", "Affirm", "large", ("fintech",)),
    RegistryCompany(_G, "gusto", "Gusto", "large", ("fintech", "hr")),
    RegistryCompany(_G, "samsara", "Samsara", "large", ("iot",)),
    RegistryCompany(_G, "scaleai", "Scale AI", "large", ("ai",), top=True),
    RegistryCompany(_G, "epicgames", "Epic Games", "large", ("gaming",), top=True),
    RegistryCompany(_G, "spacex", "SpaceX", "large", ("aerospace",), top=True),
    RegistryCompany(_G, "elastic", "Elastic", "large", ("infra",)),
    RegistryCompany(_G, "okta", "Okta", "large", ("security",)),
    RegistryCompany(_G, "pagerduty", "PagerDuty", "large", ("infra",)),
    RegistryCompany(_G, "squarespace", "Squarespace", "large", ("consumer",)),
    RegistryCompany(_G, "chime", "Chime", "large", ("fintech",)),
    RegistryCompany(_G, "doordashusa", "DoorDash", "large", ("consumer",), top=True),
    RegistryCompany(_G, "monzo", "Monzo", "large", ("fintech",)),
    RegistryCompany(_G, "klaviyo", "Klaviyo", "large", ("marketing",)),
    RegistryCompany(_G, "sofi", "SoFi", "large", ("fintech",)),
    RegistryCompany(_G, "carta", "Carta", "large", ("fintech",)),
    RegistryCompany(_G, "coursera", "Coursera", "large", ("edtech",)),
    RegistryCompany(_G, "fastly", "Fastly", "large", ("infra",)),
    RegistryCompany(_G, "cockroachlabs", "Cockroach Labs", "large", ("data",)),
    RegistryCompany(_G, "rubrik", "Rubrik", "large", ("security",)),
    RegistryCompany(_G, "zscaler", "Zscaler", "large", ("security",)),
    RegistryCompany(_G, "smartsheet", "Smartsheet", "large", ("productivity",)),
    RegistryCompany(_G, "roku", "Roku", "large", ("consumer",)),
    RegistryCompany(_G, "hubspot", "HubSpot", "large", ("marketing",)),
    RegistryCompany(_G, "toast", "Toast", "large", ("fintech",)),
    RegistryCompany(_G, "upwork", "Upwork", "large", ("marketplace",)),
    RegistryCompany(_G, "udemy", "Udemy", "large", ("edtech",)),
    RegistryCompany(_G, "block", "Block", "large", ("fintech",)),
    RegistryCompany(_G, "tripadvisor", "Tripadvisor", "large", ("travel",)),
    # 2026-08-15 list harvest (mined from the Simplify list, live-verified):
    RegistryCompany(_G, "janestreet", "Jane Street", "large", ("quant",), top=True),
    RegistryCompany(_G, "drweng", "DRW", "large", ("quant",), top=True),
    RegistryCompany(_G, "virtu", "Virtu Financial", "large", ("quant",)),
    RegistryCompany(_G, "asteraearlycareer2026", "Astera Labs", "large", ("hardware",)),
    RegistryCompany(_G, "axontalentcommunity", "Axon", "large", ("security",)),
    RegistryCompany(_G, "sharkninjaoperatingllc", "SharkNinja", "large", ("consumer",)),
    RegistryCompany(_G, "appian", "Appian", "large", ("automation",)),
    RegistryCompany(_G, "ginkgobioworks", "Ginkgo Bioworks", "large", ("biotech",)),
    # ---- greenhouse, startup ----
    RegistryCompany(_G, "vercel", "Vercel", "startup", ("devtools",), top=True),
    RegistryCompany(_G, "brex", "Brex", "startup", ("fintech",), top=True),
    RegistryCompany(_G, "flexport", "Flexport", "startup", ("logistics",)),
    RegistryCompany(_G, "airtable", "Airtable", "startup", ("productivity",)),
    RegistryCompany(_G, "checkr", "Checkr", "startup", ("hr",)),
    RegistryCompany(_G, "amplitude", "Amplitude", "startup", ("data",)),
    RegistryCompany(_G, "launchdarkly", "LaunchDarkly", "startup", ("devtools",)),
    RegistryCompany(_G, "webflow", "Webflow", "startup", ("design",)),
    RegistryCompany(_G, "calendly", "Calendly", "startup", ("productivity",)),
    RegistryCompany(_G, "lattice", "Lattice", "startup", ("hr",)),
    RegistryCompany(_G, "gongio", "Gong", "startup", ("sales",)),
    RegistryCompany(_G, "postman", "Postman", "startup", ("devtools",)),
    RegistryCompany(_G, "circleci", "CircleCI", "startup", ("devtools",)),
    # 2026-08-15 list harvest (mined from the Simplify list, live-verified):
    RegistryCompany(_G, "neuralink", "Neuralink", "startup", ("health", "hardware"), top=True),
    RegistryCompany(_G, "figureai", "Figure", "startup", ("robotics", "ai"), top=True),
    RegistryCompany(_G, "togetherai", "Together AI", "startup", ("ai", "infra")),
    RegistryCompany(_G, "cresta", "Cresta", "startup", ("ai",)),
    RegistryCompany(_G, "lilasciences", "Lila Sciences", "startup", ("ai", "biotech")),
    RegistryCompany(_G, "tenstorrentuniversity", "Tenstorrent", "startup", ("ai", "hardware")),
    RegistryCompany(_G, "astranis", "Astranis", "startup", ("aerospace",)),
    RegistryCompany(_G, "vardaspace", "Varda Space", "startup", ("aerospace",)),
    RegistryCompany(_G, "thenuclearcompany", "The Nuclear Company", "startup", ("energy",)),
    RegistryCompany(_G, "later", "Later", "startup", ("marketing",)),
    RegistryCompany(_G, "integrainterns", "Integra FEC", "startup", ("research",)),
    RegistryCompany(_G, "sevenresearch", "Seven Research", "startup"),
    RegistryCompany(_G, "dvtrading", "DV Trading", "startup", ("quant",)),
    RegistryCompany(_G, "chicagotradingcampus", "Chicago Trading Company", "startup", ("quant",)),
    RegistryCompany(_G, "mwinternshipprogram", "Marshall Wace", "startup", ("quant",)),
    RegistryCompany(_G, "transmarketgroup", "TransMarket Group", "startup", ("quant",)),
    RegistryCompany(
        _G, "walleyecapital-external-students", "Walleye Capital", "startup", ("quant",)
    ),
    RegistryCompany(
        _G, "aquaticcapitalmanagement", "Aquatic Capital Management", "startup", ("quant",)
    ),
    RegistryCompany(_G, "voloridgeinvestmentmanagement", "Voloridge", "startup", ("quant",)),
    RegistryCompany(_G, "mavensecuritiesholdingltd", "Maven Securities", "startup", ("quant",)),
    RegistryCompany(_G, "blackedgecapital", "BlackEdge Capital", "startup", ("quant",)),
    RegistryCompany(_G, "hyannisportresearch", "Hyannis Port Research", "startup", ("fintech",)),
    # ---- lever ----
    RegistryCompany(_L, "plaid", "Plaid", "large", ("fintech",), top=True),
    RegistryCompany(_L, "palantir", "Palantir", "large", ("data",), top=True),
    RegistryCompany(_L, "kraken", "Kraken", "large", ("crypto",)),
    RegistryCompany(_L, "wealthfront", "Wealthfront", "startup", ("fintech",)),
    RegistryCompany(_L, "voleon", "The Voleon Group", "startup", ("quant",)),
    RegistryCompany(_L, "zoox", "Zoox", "large", ("automotive",)),
    RegistryCompany(_L, "whoop", "WHOOP", "startup", ("health",)),
    RegistryCompany(_L, "mistral", "Mistral AI", "startup", ("ai",), top=True),
    RegistryCompany(_L, "outreach", "Outreach", "startup", ("sales",)),
    RegistryCompany(_L, "highspot", "Highspot", "startup", ("sales",)),
    RegistryCompany(_L, "veeva", "Veeva", "large", ("health",)),
    # 2026-08-15 list harvest (mined from the Simplify list, live-verified):
    RegistryCompany(_L, "tri", "Toyota Research Institute", "large", ("automotive",)),
    RegistryCompany(_L, "xsolla", "Xsolla", "startup", ("gaming",)),
    RegistryCompany(_L, "belvederetrading", "Belvedere Trading", "startup", ("quant",)),
    RegistryCompany(_L, "hermeus", "Hermeus", "startup", ("aerospace",)),
    RegistryCompany(_L, "waabi", "Waabi", "startup", ("automotive", "ai")),
    RegistryCompany(_L, "magnetforensics", "Magnet Forensics", "startup", ("security",)),
    RegistryCompany(_L, "calstart", "CALSTART", "startup", ("energy",)),
    # ---- ashby, top startups & scale-ups ----
    RegistryCompany(_A, "openai", "OpenAI", "large", ("ai",), top=True),
    RegistryCompany(_A, "linear", "Linear", "startup", ("devtools",), top=True),
    RegistryCompany(_A, "notion", "Notion", "large", ("productivity",), top=True),
    RegistryCompany(_A, "ramp", "Ramp", "large", ("fintech",), top=True),
    RegistryCompany(_A, "replit", "Replit", "startup", ("devtools",), top=True),
    RegistryCompany(_A, "cursor", "Cursor", "startup", ("ai", "devtools"), top=True),
    RegistryCompany(_A, "deel", "Deel", "large", ("hr",), top=True),
    RegistryCompany(_A, "posthog", "PostHog", "startup", ("data",)),
    RegistryCompany(_A, "zapier", "Zapier", "startup", ("productivity",)),
    RegistryCompany(_A, "vanta", "Vanta", "startup", ("security",), top=True),
    RegistryCompany(_A, "mercury", "Mercury", "startup", ("fintech",), top=True),
    RegistryCompany(_A, "supabase", "Supabase", "startup", ("devtools",), top=True),
    RegistryCompany(_A, "elevenlabs", "ElevenLabs", "startup", ("ai",), top=True),
    RegistryCompany(_A, "sierra", "Sierra", "startup", ("ai",)),
    RegistryCompany(_A, "harvey", "Harvey", "startup", ("ai", "legal")),
    RegistryCompany(_A, "modal", "Modal", "startup", ("infra",)),
    RegistryCompany(_A, "cohere", "Cohere", "startup", ("ai",)),
    RegistryCompany(_A, "docker", "Docker", "large", ("devtools",)),
    RegistryCompany(_A, "1password", "1Password", "large", ("security",)),
    RegistryCompany(_A, "clever", "Clever", "startup", ("edtech",)),
    RegistryCompany(_A, "lambda", "Lambda", "startup", ("ai", "infra")),
    RegistryCompany(_A, "eightsleep", "Eight Sleep", "startup", ("health",)),
    RegistryCompany(_A, "warp", "Warp", "startup", ("devtools",)),
    RegistryCompany(_A, "browserbase", "Browserbase", "startup", ("ai", "devtools")),
    RegistryCompany(_A, "cognition", "Cognition", "startup", ("ai",), top=True),
    RegistryCompany(_A, "suno", "Suno", "startup", ("ai",)),
    RegistryCompany(_A, "baseten", "Baseten", "startup", ("ai", "infra")),
    RegistryCompany(_A, "railway", "Railway", "startup", ("devtools",)),
    RegistryCompany(_A, "decagon", "Decagon", "startup", ("ai",)),
    # 2026-08-15 list harvest (mined from the Simplify list, live-verified):
    RegistryCompany(_A, "perplexity", "Perplexity AI", "startup", ("ai",), top=True),
    RegistryCompany(
        _A, "rivianvw.tech", "Rivian and VW Group Technologies", "large", ("automotive",)
    ),
    RegistryCompany(_A, "applied", "Applied Intuition", "startup", ("automotive", "ai")),
    RegistryCompany(_A, "etched", "Etched", "startup", ("ai", "hardware")),
    RegistryCompany(_A, "1x", "1X", "startup", ("robotics",)),
    RegistryCompany(_A, "skydio", "Skydio", "startup", ("robotics",)),
    RegistryCompany(_A, "persona.ai", "Persona AI", "startup", ("robotics",)),
    RegistryCompany(_A, "base-power", "Base Power", "startup", ("energy",)),
    RegistryCompany(_A, "tilderesearch", "Tilde Research", "startup", ("ai",)),
    RegistryCompany(_A, "meshy", "Meshy", "startup", ("ai",)),
    RegistryCompany(_A, "opusclip", "OpusClip", "startup", ("ai",)),
    RegistryCompany(_A, "netic", "Cybernetic Labs", "startup", ("ai",)),
    RegistryCompany(_A, "melotech", "Melotech", "startup"),
    RegistryCompany(_A, "super.com", "Super", "startup", ("consumer",)),
    # ---- smartrecruiters (enterprise) ----
    RegistryCompany(_S, "BoschGroup", "Bosch", "large", ("hardware",), top=True),
    RegistryCompany(_S, "ServiceNow", "ServiceNow", "large", ("infra",), top=True),
    RegistryCompany(_S, "Ubisoft2", "Ubisoft", "large", ("gaming",)),
    RegistryCompany(_S, "Visa", "Visa", "large", ("fintech",), top=True),
    RegistryCompany(_S, "McDonaldsCorporation", "McDonald's", "large", ("consumer",)),
    RegistryCompany(_S, "Experian", "Experian", "large", ("fintech",)),
    # 2026-08-15 list harvest (mined from the Simplify list, live-verified):
    RegistryCompany(_S, "Canva", "Canva", "large", ("design",), top=True),
    RegistryCompany(_S, "WesternDigital", "Western Digital", "large", ("hardware",)),
    RegistryCompany(_S, "NorthwesternMutual", "Northwestern Mutual", "large", ("insurance",)),
    RegistryCompany(
        _S, "LLNL", "Lawrence Livermore National Laboratory", "large", ("research",)
    ),
    # ---- workable ----
    # 2026-08-15 adapter probe (mined from the Simplify list, live-verified):
    RegistryCompany(_W, "thorlabs", "Thorlabs", "large", ("hardware",)),
    RegistryCompany(_W, "pony-dot-ai", "Pony.ai", "large", ("automotive", "ai")),
    RegistryCompany(_W, "onlogic-inc", "OnLogic", "startup", ("hardware",)),
)
