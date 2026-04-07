import subprocess
from urllib.parse import urlparse
from tools.registry import tool

BRAVE_PATH = r"/mnt/c/Program Files/BraveSoftware/Brave-Browser/Application/brave.exe"


@tool
def open_browser(url: str) -> str:
    """Open a URL in Brave browser on the host machine."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return f"Refused: only http/https URLs are allowed, got '{parsed.scheme}'."

    try:
        subprocess.Popen(
            [BRAVE_PATH, url],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return f"Opened {url} in Brave."
    except FileNotFoundError:
        return "Brave browser not found at the expected path."
    except Exception as exc:
        return f"Failed to open browser: {exc}"
