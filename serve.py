#!/usr/bin/env python3
"""Convenience launcher for the JARVIS web app: `python serve.py`.

Serves the installable PWA + API so you can use JARVIS from your phone's
browser while the model and tools run here on your machine.
"""

from jarvis.web.__main__ import main

if __name__ == "__main__":
    main()
