"""
Application configuration via Pydantic Settings.
Values can be overridden by environment variables (prefixed VOWCUT_).
"""
from __future__ import annotations

import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VOWCUT_", env_file=".env", extra="ignore")

    # Directory under which per-job project folders are created
    projects_base_dir: str = str(Path.home() / "VowCut" / "projects")

    # Optional explicit paths (empty → auto-detect via PATH)
    ffmpeg_path: str = ""
    ffprobe_path: str = ""

    # Server
    host: str = "127.0.0.1"
    port: int = 0          # 0 → OS assigns a free port; actual port printed to stdout

    # Export defaults
    default_export_mode: str = "fast_gpu"
    default_music_volume: float = 0.6
    default_target_length_s: float = 240.0

    # Feature extraction
    chunk_duration_s: float = 2.0


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
        Path(_settings.projects_base_dir).mkdir(parents=True, exist_ok=True)
    return _settings
