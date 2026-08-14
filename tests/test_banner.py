"""The interactive ASCII-wordmark banner."""

import re

from interninbox.banner import render_banner

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_TAGLINE = "find internships. in the terminal."


def test_plain_banner_is_multiline_ascii_without_escapes() -> None:
    text = render_banner(color=False)
    assert "\x1b" not in text
    assert len(text.splitlines()) >= 6  # a real wordmark, not a one-liner
    assert _TAGLINE in text
    text.encode("cp437")  # pure ASCII art: safe on any console, incl. legacy Windows


def test_colored_banner_uses_theme_proof_blue_and_always_resets() -> None:
    text = render_banner(color=True)
    assert "\x1b[38;5;" in text  # a 256-color index, not a themeable 16-color slot
    # No styled line may leak color past its end.
    assert all(line.endswith("\x1b[0m") for line in text.splitlines() if line.strip())
    # Stripping the escapes leaves exactly the plain banner.
    assert _ANSI.sub("", text) == render_banner(color=False)
