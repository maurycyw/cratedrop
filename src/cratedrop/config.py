"""User configuration: ~/.config/cratedrop/config.toml.

Only two settings for Stage 1 — the staging dir (inbox the user drops audio
into) and the processed dir (the maintained USB image tree). Both later move
to a NAS; keeping them as plain paths makes that a config-only change.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("CRATEDROP_CONFIG_DIR",
                                 Path.home() / ".config" / "cratedrop"))
CONFIG_PATH = CONFIG_DIR / "config.toml"

SETTING_KEYS = ("staging-dir", "processed-dir", "playlists-by-date", "playlists-from-folders")


@dataclass
class Config:
    staging_dir: Path | None = None
    processed_dir: Path | None = None
    playlists_by_date: bool = True      # MM/DD/YYYY ingest-day playlists
    playlists_from_folders: bool = False  # top-level staging folders -> playlists

    @classmethod
    def load(cls) -> "Config":
        if not CONFIG_PATH.exists():
            return cls()
        raw = tomllib.loads(CONFIG_PATH.read_text())
        def _path(key: str) -> Path | None:
            v = raw.get(key)
            return Path(v).expanduser() if v else None
        return cls(staging_dir=_path("staging-dir"),
                   processed_dir=_path("processed-dir"),
                   playlists_by_date=bool(raw.get("playlists-by-date", True)),
                   playlists_from_folders=bool(raw.get("playlists-from-folders", False)))

    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        lines = []
        if self.staging_dir:
            lines.append(f'staging-dir = "{self.staging_dir}"')
        if self.processed_dir:
            lines.append(f'processed-dir = "{self.processed_dir}"')
        lines.append(f"playlists-by-date = {str(self.playlists_by_date).lower()}")
        lines.append(f"playlists-from-folders = {str(self.playlists_from_folders).lower()}")
        CONFIG_PATH.write_text("\n".join(lines) + "\n")

    @staticmethod
    def _bool(value: str) -> bool:
        if value.lower() in ("true", "yes", "on", "1"):
            return True
        if value.lower() in ("false", "no", "off", "0"):
            return False
        raise KeyError(f"expected true/false, got {value!r}")

    def set(self, key: str, value: str) -> None:
        if key == "playlists-by-date":
            self.playlists_by_date = self._bool(value)
            return
        if key == "playlists-from-folders":
            self.playlists_from_folders = self._bool(value)
            return
        path = Path(value).expanduser().resolve()
        if key == "staging-dir":
            self.staging_dir = path
        elif key == "processed-dir":
            self.processed_dir = path
        else:
            raise KeyError(f"unknown setting {key!r}; valid: {', '.join(SETTING_KEYS)}")

    def require(self, key: str) -> Path:
        val = {"staging-dir": self.staging_dir,
               "processed-dir": self.processed_dir}[key]
        if val is None:
            raise RuntimeError(
                f"{key} is not configured; run: cratedrop config set {key} <path>")
        return val
