"""The block-wordmark banner shown at the top of an interactive scan.

A bold lowercase "interninbox" built from solid block glyphs, mirroring the
logo: "intern" in white, "inbox" in blue, with the tagline typed at a prompt
below. Kept pure so it is easy to test; the CLI decides *whether* to show it
(a real terminal, not piped, `NO_COLOR` honored) and this module only decides
*how* it looks.

Every glyph is a space or one of the cp437 block characters (full block, top
half, bottom half), so the banner encodes on a legacy Windows console and
never turns to mojibake. The accent is a 256-color blue index rather than a
16-color slot, so a theme that remaps "bright blue" to purple cannot recolor
it. Color is optional and every styled line resets, so nothing leaks.
"""

from __future__ import annotations

_INTERN = (
    "██        ██",
    "          ██",
    "██ ██████ ██▀▀▀▀ ██████ ██▀▀██ ██████",
    "██ ██  ██ ██     ██▄▄██ ██     ██  ██",
    "██ ██  ██ ██     ██     ██     ██  ██",
    "██ ██  ██  ▀████ ██████ ██     ██  ██",
)
_INBOX = (
    "██        ██",
    "          ██",
    "██ ██████ ██████ ██████ ██  ██",
    "██ ██  ██ ██  ██ ██  ██  ▀██▀",
    "██ ██  ██ ██  ██ ██  ██  ▄██▄",
    "██ ██  ██ ██████ ██████ ██  ██",
)
_INTERN_WIDTH = max(len(row) for row in _INTERN)
_GAP = 3
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
            lines.append(f"{_BOLD}{left}{_BLUE}{inbox_row}{_RESET}".rstrip() + _RESET)
        else:
            lines.append((left + inbox_row).rstrip())
    lines.append("")
    if color:
        # The tagline's periods pick up the logo's blue, like the artwork.
        tagline = _TAGLINE.replace(".", f"{_RESET}{_BLUE}.{_RESET}{_DIM}")
        lines.append(f"  {_BLUE}>{_RESET} {_DIM}{tagline}{_RESET}")
    else:
        lines.append(f"  > {_TAGLINE}")
    return "\n".join(lines)
