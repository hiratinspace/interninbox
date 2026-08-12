"""The one-line banner shown at the top of an interactive scan.

Kept tiny and pure so it is easy to test and easy to reason about. The CLI
decides *whether* to show it (a real terminal, not piped, `NO_COLOR` honored);
this module only decides *how* it looks. Pure ASCII, so it renders on any
console; the blue accent and dim tagline echo the logo.
"""

from __future__ import annotations

_WORDMARK_A = "intern"
_WORDMARK_B = "inbox"
_TAGLINE = "find internships. in the terminal."

_BOLD = "\x1b[1m"
_BLUE = "\x1b[94m"
_DIM = "\x1b[2m"
_RESET = "\x1b[0m"


def render_banner(*, color: bool) -> str:
    """The banner line, with ANSI styling when `color` is true, else plain."""
    if not color:
        return f"{_WORDMARK_A}{_WORDMARK_B}  >  {_TAGLINE}"
    return (
        f"{_BOLD}{_WORDMARK_A}{_BLUE}{_WORDMARK_B}{_RESET}"  # intern (bold) + inbox (bold blue)
        f"  {_BLUE}>{_RESET}  "  # the terminal-prompt accent
        f"{_DIM}{_TAGLINE}{_RESET}"  # dimmed tagline
    )
