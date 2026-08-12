"""The interactive terminal-window banner."""

import re

from interninbox.banner import render_banner

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_TAGLINE = "find internships. in the terminal."


def test_plain_banner_is_an_aligned_box_without_escape_codes() -> None:
    text = render_banner(color=False)
    assert "\x1b" not in text
    lines = text.splitlines()
    assert len(lines) == 4  # top, title, prompt, bottom
    assert lines[0][0] == "┌" and lines[0][-1] == "┐"
    assert lines[-1][0] == "└" and lines[-1][-1] == "┘"
    assert all(line[0] in "┌│└" and line[-1] in "┐│┘" for line in lines)
    # every line is the same visual width (all glyphs are single-width here)
    assert len({len(line) for line in lines}) == 1
    assert "interninbox" in text
    assert _TAGLINE in text


def test_colored_banner_styles_every_line_and_always_resets() -> None:
    text = render_banner(color=True)
    assert "\x1b[" in text
    # No line may leak styling past its right border.
    assert all(line.endswith("\x1b[0m") for line in text.splitlines())
    # Stripping the escapes leaves the same box as the plain version.
    assert _ANSI.sub("", text) == render_banner(color=False)


def test_banner_glyphs_are_cp437_safe() -> None:
    # Only box-drawing, the full block, and ASCII: encodable on a legacy
    # Windows console, so an interactive scan never mojibakes.
    render_banner(color=False).encode("cp437")
