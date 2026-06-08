from __future__ import annotations

from datetime import datetime
from pathlib import Path


class FileReportWriter:
    """Persists daily maintainer reports under a local directory."""

    def __init__(self, directory: Path):
        self.directory = directory

    def write(self, date_key: str, content: str) -> str:
        self.directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%H%M%S")
        path = self.directory / f"{date_key}-{stamp}.txt"
        path.write_text(content, encoding="utf-8")
        return str(path)


class FixedPathReportWriter:
    """Persists a report to an explicit file path."""

    def __init__(self, path: Path):
        self.path = path

    def write(self, date_key: str, content: str) -> str:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(content, encoding="utf-8")
        return str(self.path)
