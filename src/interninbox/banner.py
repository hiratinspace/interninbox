"""The little terminal-window banner shown at the top of an interactive scan.

Rendered as a framed pane that looks like the logo's terminal: window dots,
the two-tone wordmark as the title, and the tagline typed at a prompt with a
block cursor. Kept pure so it is easy to test; the CLI decides *whether* to
show it (a real terminal, not piped, `NO_COLOR` honored) and this module only
decides *how* it looks.

Every glyph is box-drawing, the full block, or ASCII, so it encodes on a
legacy Windows console (cp437) and never turns to mojibake. Color is optional
and, when on, every line resets its own styling so nothing leaks past the box.
"""

from __future__ import annotations

_TAGLINE = "find internships. in the terminal."
_CURSOR = "█"  # full block; cp437 0xDB

_RED = "\x1b[31m"
_YELLOW = "\x1b[33m"
_GREEN = "\x1b[32m"
_BLUE = "\x1b[94m"
_BOLD = "\x1b[1m"
_DIM = "\x1b[2m"
_RESET = "\x1b[0m"


def render_banner(*, color: bool) -> str:
    """A four-line boxed banner, styled with ANSI when `color` is true."""
    # Each content row as (visible text, styled text). Widths are measured on
    # the visible text so the box stays aligned regardless of escape codes.
    title = (
        "o o o   interninbox",
        f"{_RED}o{_RESET} {_YELLOW}o{_RESET} {_GREEN}o{_RESET}   "
        f"{_BOLD}intern{_BLUE}inbox{_RESET}",
    )
    prompt = (
        f"> {_TAGLINE} {_CURSOR}",
        f"{_BLUE}>{_RESET} {_DIM}{_TAGLINE}{_RESET} {_BLUE}{_CURSOR}{_RESET}",
    )
    rows = [title, prompt]
    inner = max(len(plain) for plain, _ in rows)

    edge = _DIM if color else ""
    reset = _RESET if color else ""
    top = f"{edge}┌{'─' * (inner + 2)}┐{reset}"
    bottom = f"{edge}└{'─' * (inner + 2)}┘{reset}"

    lines = [top]
    for plain, styled in rows:
        body = (styled if color else plain) + " " * (inner - len(plain))
        lines.append(f"{edge}│{reset} {body} {edge}│{reset}")
    lines.append(bottom)
    return "\n".join(lines)
