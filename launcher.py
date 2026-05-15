#!/usr/bin/env python3
"""
launcher.py — Production WSGI entry point for Anki ESH.

Used in two ways:
  1. Standalone: `python launcher.py` (opens browser)
  2. Tauri sidecar: launched automatically by the Tauri app (no browser)

Set environment variable ANKI_ESH_SIDECAR=1 to suppress browser opening.
"""

import os
import socket
import sys
import threading
import webbrowser

from waitress import serve

from app import app

PORT = 5000


def find_free_port(start=5000, end=5100):
    """Find a free port so we never collide with another app."""
    for port in range(start, end):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return start


def open_browser(port):
    """Open the browser after a short delay so the server is ready."""
    import time
    time.sleep(1.0)
    webbrowser.open(f"http://127.0.0.1:{port}")


def main():
    port = find_free_port(start=PORT)

    is_sidecar = os.environ.get("ANKI_ESH_SIDECAR") == "1"

    print(f"Anki ESH running on http://127.0.0.1:{port}", flush=True)

    if not is_sidecar:
        print("   Close this window to stop the server.\n")
        threading.Thread(target=open_browser, args=(port,), daemon=True).start()

    serve(app, host="127.0.0.1", port=port, threads=4)


if __name__ == "__main__":
    main()
