"""Register (or remove) the ansysguide:// URL protocol for the current user.

Lets the web app's "Launch desktop guide" button start the guided overlay on
this PC. Writes to HKEY_CURRENT_USER only — no admin rights needed. Run once
per lab PC (part of lab-PC setup):

    .venv\\Scripts\\python tools\\register_guide_protocol.py            # register
    .venv\\Scripts\\python tools\\register_guide_protocol.py --unregister
"""

import sys
import winreg
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = REPO_ROOT / "tools" / "guide_launcher.py"
PYTHONW = REPO_ROOT / ".venv" / "Scripts" / "pythonw.exe"
SCHEME = "ansysguide"


def register() -> None:
    if not PYTHONW.is_file():
        sys.exit(f"venv python not found at {PYTHONW} — create the venv first")
    command = f'"{PYTHONW}" "{LAUNCHER}" "%1"'
    root = winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{SCHEME}")
    winreg.SetValueEx(root, None, 0, winreg.REG_SZ, "URL:Ansys Guide")
    winreg.SetValueEx(root, "URL Protocol", 0, winreg.REG_SZ, "")
    cmd_key = winreg.CreateKey(root, r"shell\open\command")
    winreg.SetValueEx(cmd_key, None, 0, winreg.REG_SZ, command)
    winreg.CloseKey(cmd_key)
    winreg.CloseKey(root)
    print(f"registered {SCHEME}:// -> {command}")
    print("The web app's 'Launch desktop guide' button now works in browsers on this PC.")


def unregister() -> None:
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{SCHEME}\shell\open\command")
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{SCHEME}\shell\open")
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{SCHEME}\shell")
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{SCHEME}")
        print(f"unregistered {SCHEME}://")
    except FileNotFoundError:
        print(f"{SCHEME}:// was not registered")


if __name__ == "__main__":
    if "--unregister" in sys.argv[1:]:
        unregister()
    else:
        register()
