#!/usr/bin/env python3
"""
DockerDeck v3 — Docker Package & Deploy Suite
Entry point.

Run:
    python main.py

Requirements:
    Python 3.8+ with tkinter (stdlib only — no pip installs required)
"""

import sys
import os

# Ensure the package directory is on the path when run directly
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

from app import DockerDeck


def main():
    app = DockerDeck()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()


if __name__ == "__main__":
    main()
