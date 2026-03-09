#!/usr/bin/env python3
"""
DockerDeck v4 — Local Docker Operator Console
Entry point.

Run:
    python main.py
    python main.py --debug          # verbose logging to stderr
    python main.py --log FILE       # also write log to FILE

Requirements:
    Python 3.8+ with tkinter (stdlib only — no pip installs required)
"""

import sys
import os
import argparse
import logging

# Ensure the package directory is on the path when run directly
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

from utils import configure_logging
from app import DockerDeck


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="DockerDeck — local Docker operator console")
    p.add_argument("--debug", action="store_true",
                   help="Enable verbose debug logging to stderr")
    p.add_argument("--log", metavar="FILE",
                   help="Also write logs to FILE")
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    level = logging.DEBUG if args.debug else logging.WARNING
    configure_logging(level=level, log_file=args.log)

    app = DockerDeck()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()


if __name__ == "__main__":
    main()
