"""The interactive one-line banner."""

import re

from interninbox.banner import render_banner

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def test_plain_banner_has_no_escape_codes() -> None:
    text = render_banner(color=False)
    assert "\x1b" not in text
    assert text == "interninbox  >  find internships. in the terminal."


def test_colored_banner_wraps_the_same_visible_text() -> None:
    text = render_banner(color=True)
    assert "\x1b[" in text  # has ANSI
    assert text.endswith("\x1b[0m")  # ends with a reset, never leaks style
    # Stripping the escapes leaves exactly the plain banner.
    assert _ANSI.sub("", text) == "interninbox  >  find internships. in the terminal."
