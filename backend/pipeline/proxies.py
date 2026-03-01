"""
Proxy generation stage: 720p@30 H.264 proxy + mono WAV audio extraction.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from .accel import ffmpeg_proxy_args
from .types import Manifest
from .utils import ProgressEmitter, log_path, manifest_write


def _make_proxy(
    ffmpeg: str,
    source_path: str,
    proxy_path: Path,
    codec_args: list[str],
    log_fh,
    emitter: ProgressEmitter,
    step_label: str,
) -> None:
    proxy_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        ffmpeg,
        "-y",
        "-i", source_path,
        *codec_args,
        "-an",            # no audio in proxy
        "-movflags", "+faststart",
        str(proxy_path),
    ]
    log_fh.write(f"[proxy] {' '.join(cmd)}\n")

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    for line in proc.stdout:
        log_fh.write(line)
        if "frame=" in line:
            emitter.emit("proxy", "running", -1, f"{step_label}: {line.strip()}")

    proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(f"Proxy encode failed for {source_path} (exit {proc.returncode})")


def _extract_audio(
    ffmpeg: str,
    source_path: str,
    wav_path: Path,
    log_fh,
) -> None:
    wav_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        ffmpeg,
        "-y",
        "-i", source_path,
        "-vn",
        "-ac", "1",              # mono
        "-ar", "44100",
        "-f", "wav",
        str(wav_path),
    ]
    log_fh.write(f"[audio] {' '.join(cmd)}\n")

    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=300,
    )
    log_fh.write(result.stdout)
    if result.returncode != 0:
        raise RuntimeError(f"Audio extraction failed for {source_path} (exit {result.returncode})")


def run(
    project_dir: Path,
    manifest: Manifest,
    emitter: ProgressEmitter,
) -> Manifest:
    """
    Proxy stage:
    1. Encode 720p@30 H.264 proxy for each source.
    2. Extract mono WAV audio.
    3. Update manifest with proxy_path / audio_path.

    Idempotent — skips if stage_status.proxy == "done".
    """
    if manifest.stage_status.proxy == "done":
        emitter.emit("proxy", "done", 1.0, "Skipped (already done)")
        return manifest

    emitter.emit("proxy", "running", 0.0, "Starting proxy generation")
    manifest.stage_status.proxy = "running"
    manifest_write(project_dir, manifest)

    ffmpeg = manifest.accel.ffmpeg_path if manifest.accel else "ffmpeg"
    codec_args = ffmpeg_proxy_args(manifest.accel) if manifest.accel else [
        "-c:v", "libx264", "-preset", "fast", "-crf", "23", "-vf", "scale=-2:720", "-r", "30"
    ]

    log_file = log_path(project_dir, "proxy")
    proxies_dir = project_dir / "proxies"
    audio_dir = project_dir / "audio"

    with log_file.open("w") as log:
        n = len(manifest.sources)
        for i, source in enumerate(manifest.sources):
            base_progress = i / max(n, 1)
            label = f"cam {source.id}"

            proxy_path = proxies_dir / f"{source.id}_proxy.mp4"
            wav_path = audio_dir / f"{source.id}.wav"

            try:
                emitter.emit("proxy", "running", base_progress, f"Encoding proxy: {label}")
                _make_proxy(ffmpeg, source.original_path, proxy_path, codec_args, log, emitter, label)
                source.proxy_path = str(proxy_path)

                emitter.emit("proxy", "running", base_progress + 0.4 / max(n, 1), f"Extracting audio: {label}")
                _extract_audio(ffmpeg, source.original_path, wav_path, log)
                source.audio_path = str(wav_path)

            except Exception as e:
                manifest.stage_status.proxy = "error"
                manifest.pipeline.error = str(e)
                manifest_write(project_dir, manifest)
                emitter.emit("proxy", "error", base_progress, str(e))
                raise

    manifest.stage_status.proxy = "done"
    manifest_write(project_dir, manifest)
    emitter.emit("proxy", "done", 1.0, f"Proxies complete for {n} source(s)")
    return manifest
