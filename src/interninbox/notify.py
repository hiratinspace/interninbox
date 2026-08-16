"""Best-effort desktop notifications for watch mode.

One function, `send(title, body)`, dispatches to the native notifier for the
current platform: `osascript` on macOS, `notify-send` on Linux, a PowerShell
toast on Windows. Any other platform is a silent no-op. Every failure (missing
binary, hung notifier, anything the runner raises) is swallowed: a
notification is a nicety, never worth crashing the watch loop over.

The runner is injectable so tests can assert the constructed commands without
spawning real processes (and without popping real notifications).
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable

_TIMEOUT_SECONDS = 10  # a hung notifier must not stall the watch loop

# PowerShell toast via the WinRT API: no modules to install, ships with
# Windows 10+. Title and body are spliced in as single-quoted literals.
_POWERSHELL_TOAST = """\
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, \
ContentType = WindowsRuntime] | Out-Null
$template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent(\
[Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$texts = $template.GetElementsByTagName('text')
$texts.Item(0).AppendChild($template.CreateTextNode('{title}')) | Out-Null
$texts.Item(1).AppendChild($template.CreateTextNode('{body}')) | Out-Null
$toast = [Windows.UI.Notifications.ToastNotification]::new($template)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier(\
'interninbox').Show($toast)
"""


def send(title: str, body: str, *, runner: Callable[..., object] = subprocess.run) -> None:
    """Show a desktop notification, best effort: never raises, no-op if unsupported."""
    command = _command(sys.platform, title, body)
    if command is None:
        return
    try:
        runner(command, capture_output=True, timeout=_TIMEOUT_SECONDS, check=False)
    except Exception:  # best effort by contract: swallow everything
        return


def _command(platform: str, title: str, body: str) -> list[str] | None:
    """The notifier invocation for a platform, or None when there is none."""
    if platform == "darwin":
        script = (
            f"display notification {_applescript_string(body)} "
            f"with title {_applescript_string(title)}"
        )
        return ["osascript", "-e", script]
    if platform.startswith("linux"):
        return ["notify-send", title, body]
    if platform == "win32":
        script = _POWERSHELL_TOAST.format(
            title=_powershell_literal(title), body=_powershell_literal(body)
        )
        return ["powershell", "-NoProfile", "-NonInteractive", "-Command", script]
    return None


def _applescript_string(text: str) -> str:
    """Quote text as an AppleScript string literal (backslash escaping)."""
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _powershell_literal(text: str) -> str:
    """Escape text for splicing inside a single-quoted PowerShell string."""
    return text.replace("'", "''")
