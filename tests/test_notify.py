"""Best-effort desktop notifications: command shape per platform, never a crash."""

import subprocess
import sys

import pytest

from interninbox.notify import send


class RecordingRunner:
    """A fake subprocess.run that records every call instead of spawning."""

    def __init__(self) -> None:
        self.calls: list[tuple[list[str], dict]] = []

    def __call__(self, command: list[str], **kwargs) -> None:
        self.calls.append((command, kwargs))


def test_darwin_uses_osascript_display_notification(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    runner = RecordingRunner()
    send("3 new internships", "Tesla: Software Intern", runner=runner)
    ((command, kwargs),) = runner.calls
    assert command[0] == "osascript"
    assert command[1] == "-e"
    script = command[2]
    assert "display notification" in script
    assert "with title" in script
    assert "3 new internships" in script
    assert "Tesla: Software Intern" in script
    # Notifier output must never leak into the watch terminal.
    assert kwargs.get("capture_output") is True


def test_darwin_escapes_quotes_and_backslashes_for_applescript(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    runner = RecordingRunner()
    send('say "hi"', "a \\ backslash", runner=runner)
    ((command, _),) = runner.calls
    script = command[2]
    assert '\\"hi\\"' in script  # quotes escaped, so the script stays one string
    assert "a \\\\ backslash" in script


def test_linux_uses_notify_send(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    runner = RecordingRunner()
    send("3 new internships", "Tesla: Software Intern", runner=runner)
    ((command, _),) = runner.calls
    assert command == ["notify-send", "3 new internships", "Tesla: Software Intern"]


def test_win32_uses_a_powershell_toast(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    runner = RecordingRunner()
    send("3 new internships", "Tesla: Software Intern", runner=runner)
    ((command, _),) = runner.calls
    assert command[0] == "powershell"
    assert "-Command" in command
    script = command[-1]
    assert "ToastNotification" in script
    assert "3 new internships" in script
    assert "Tesla: Software Intern" in script


def test_win32_doubles_single_quotes_for_powershell(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    runner = RecordingRunner()
    send("it's here", "don't miss it", runner=runner)
    ((command, _),) = runner.calls
    script = command[-1]
    assert "it''s here" in script
    assert "don''t miss it" in script


def test_unknown_platform_is_a_silent_no_op(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "sunos5")
    runner = RecordingRunner()
    send("Title", "Body", runner=runner)
    assert runner.calls == []


@pytest.mark.parametrize("platform", ["darwin", "linux", "win32"])
@pytest.mark.parametrize(
    "error",
    [
        FileNotFoundError("notifier binary missing"),
        subprocess.TimeoutExpired(cmd="notifier", timeout=10),
        OSError("cannot spawn"),
        RuntimeError("anything else"),
    ],
)
def test_a_failing_runner_is_swallowed(monkeypatch, platform, error) -> None:
    monkeypatch.setattr(sys, "platform", platform)

    def boom(command: list[str], **kwargs) -> None:
        raise error

    send("Title", "Body", runner=boom)  # must not raise
