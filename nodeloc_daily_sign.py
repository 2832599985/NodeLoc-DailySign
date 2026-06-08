#!/usr/bin/env python3
"""Compatibility entry point for NodeLoc daily check-in."""

from __future__ import annotations

import sys

from nodeloc_maintainer.interfaces.cli import main


if __name__ == "__main__":
    sys.exit(main())
