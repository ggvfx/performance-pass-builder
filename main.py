"""
Main Application Entry Point.

Starts the local web server and opens the app in the default browser.
No pipeline work happens here — this only gets the app on screen.
"""

import logging
import threading
import webbrowser

import uvicorn

from src.core.config import APP_NAME, HOST, PORT

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')


def open_browser_when_ready(url: str, delay_seconds: float = 1.0):
    """
    Opens the UI in the user's browser shortly after the server starts.

    Args:
        url: The address the server is listening on.
        delay_seconds: Small head start so the first request does not race
            the server coming up.
    """
    threading.Timer(delay_seconds, lambda: webbrowser.open(url)).start()


def main():
    """Launches the FastAPI app on localhost."""
    url = f"http://{HOST}:{PORT}"

    logging.info(f"Starting {APP_NAME} at {url}")
    open_browser_when_ready(url)

    # Bound to loopback deliberately. The path picker will list this machine's
    # filesystem, so the server must never be reachable from the network.
    uvicorn.run("src.ui.server:app", host=HOST, port=PORT, log_level="info")


if __name__ == "__main__":
    main()
