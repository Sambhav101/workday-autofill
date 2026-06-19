"""Best-effort, cross-platform desktop notification. Always a no-op on failure —
notifications are a nicety, never a reason to break a run."""
from __future__ import annotations

import subprocess
import sys


def notify(title: str, message: str) -> None:
    """Ping the user: macOS toast / Windows beep / Linux notify-send. Never raises."""
    try:
        if sys.platform == "darwin":
            safe = lambda s: s.replace('"', "'")
            subprocess.run(
                ["osascript", "-e",
                 f'display notification "{safe(message)}" with title "{safe(title)}" '
                 f'sound name "Glass"'],
                check=False, capture_output=True, timeout=5)
        elif sys.platform == "win32":
            import winsound  # stdlib on Windows
            winsound.MessageBeep()
        else:  # linux / other
            subprocess.run(["notify-send", title, message],
                           check=False, capture_output=True, timeout=5)
    except Exception:  # noqa: BLE001
        pass
