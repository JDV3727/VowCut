"""
Application configuration via Pydantic Settings.
Values can be overridden by environment variables (prefixed VOWCUT_).
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


def _resolve_tool(name: str) -> str:
    """
    Resolve a tool binary (e.g. "ffmpeg", "ffprobe") using this priority:
    1. Explicit env var VOWCUT_FFMPEG_PATH (for "ffmpeg") or VOWCUT_FFPROBE_PATH
    2. Bundled binary at $VOWCUT_RESOURCES_PATH/ffmpeg/{name}
    3. System PATH (shutil.which)
    Falls back to the bare name if nothing is found.
    """
    # 1. Explicit env var
    env_key = f"VOWCUT_{name.upper()}_PATH"
    env_val = os.environ.get(env_key, "")
    if env_val and Path(env_val).exists():
        return env_val

    # 2. Bundled binary
    resources_path = os.environ.get("VOWCUT_RESOURCES_PATH", "")
    if resources_path:
        bundled = Path(resources_path) / "ffmpeg" / name
        if bundled.exists():
            return str(bundled)

    # 3. System PATH
    found = shutil.which(name)
    if found:
        return found

    return name


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VOWCUT_", env_file=".env", extra="ignore")

    # Directory under which per-job project folders are created
    projects_base_dir: str = str(Path.home() / "VowCut" / "projects")

    # Optional explicit paths (empty → auto-detect via PATH / bundled binary)
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

    def __init__(self, **data):
        super().__init__(**data)
        # If no explicit ffmpeg/ffprobe path was set, try bundled then system PATH
        if not self.ffmpeg_path:
            self.ffmpeg_path = _resolve_tool("ffmpeg")
        if not self.ffprobe_path:
            self.ffprobe_path = _resolve_tool("ffprobe")


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
        Path(_settings.projects_base_dir).mkdir(parents=True, exist_ok=True)
    return _settings
