"""The ASCII-wordmark banner shown at the top of an interactive scan.

A big two-tone "interninbox" (figlet "slant"), split so "intern" and "inbox"
carry the logo's white/blue, with the tagline typed at a prompt below. Kept
pure so it is easy to test; the CLI decides *whether* to show it (a real
terminal, not piped, `NO_COLOR` honored) and this module only decides *how* it
looks.

The art is pure ASCII, so the whole banner encodes on a legacy Windows console
and never mojibakes. The accent is a 256-color blue index rather than a 16-color
slot, so a theme that remaps "bright blue" to purple cannot recolor it. Color
is optional and every styled line resets, so nothing leaks past the wordmark.
"""

from __future__ import annotations

_INTERN = (
    "    _       __",
    "   (_)___  / /____  _________",
    "  / / __ \\/ __/ _ \\/ ___/ __ \\",
    " / / / / / /_/  __/ /  / / / /",
    "/_/_/ /_/\\__/\\___/_/  /_/ /_/",
)
_INBOX = (
    "    _       __",
    "   (_)___  / /_  ____  _  __",
    "  / / __ \\/ __ \\/ __ \\| |/_/",
    " / / / / / /_/ / /_/ />  <",
    "/_/_/ /_/_.___/\\____/_/|_|",
)
_INTERN_WIDTH = max(len(row) for row in _INTERN)
_GAP = 2
_TAGLINE = "find internships. in the terminal."

_BLUE = "\x1b[38;5;33m"
_BOLD = "\x1b[1m"
_DIM = "\x1b[2m"
_RESET = "\x1b[0m"


def render_banner(*, color: bool) -> str:
    """The multi-line banner, styled with ANSI when `color` is true."""
    lines: list[str] = []
    for intern_row, inbox_row in zip(_INTERN, _INBOX, strict=True):
        left = intern_row.ljust(_INTERN_WIDTH + _GAP)
        if color:
            lines.append(f"{_BOLD}{left}{_BLUE}{inbox_row}{_RESET}")
        else:
            lines.append(f"{left}{inbox_row}")
    lines.append("")
    if color:
        lines.append(f"  {_BLUE}>{_RESET} {_DIM}{_TAGLINE}{_RESET}")
    else:
        lines.append(f"  > {_TAGLINE}")
    return "\n".join(lines)
