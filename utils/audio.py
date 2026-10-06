"""Upload validation, duration detection and temporary-file handling."""

from __future__ import annotations

import contextlib
import io
import os
import tempfile
import wave
from collections.abc import Iterator
from pathlib import Path

from config import MAX_UPLOAD_BYTES, MAX_UPLOAD_MB, SUPPORTED_AUDIO_TYPES, SUPPORTED_EXTENSIONS
from errors import EmptyFileError, FileTooLargeError, UnsupportedFileError


def get_extension(filename: str) -> str:
    """Lower-cased extension including the dot ('' if none)."""
    return Path(filename).suffix.lower()


_PLAYBACK_MIME = {
    ".mp3": "audio/mpeg", ".mpeg": "audio/mpeg", ".wav": "audio/wav",
    ".m4a": "audio/mp4", ".mp4": "audio/mp4", ".webm": "audio/webm",
}


def playback_mime(filename: str) -> str:
    """MIME type for the browser audio player (not the type sent to Gemini)."""
    return _PLAYBACK_MIME.get(get_extension(filename), "audio/wav")


def validate_upload(filename: str, size_bytes: int) -> str:
    """Validate an upload and return its MIME type; raise a UserFacingError if invalid."""
    ext = get_extension(filename)
    if ext not in SUPPORTED_AUDIO_TYPES:
        supported = ", ".join(e.upper() for e in SUPPORTED_EXTENSIONS)
        raise UnsupportedFileError(
            f"'{ext or filename}' is not a supported recording format. Supported formats: {supported}."
        )
    if size_bytes <= 0:
        raise EmptyFileError("The uploaded recording is empty (0 bytes).")
    if size_bytes > MAX_UPLOAD_BYTES:
        raise FileTooLargeError(
            f"The recording is {format_size(size_bytes)}, which exceeds the {MAX_UPLOAD_MB} MB limit."
        )
    return SUPPORTED_AUDIO_TYPES[ext]


def format_size(size_bytes: int) -> str:
    """Human-readable file size."""
    size = float(size_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size_bytes} B"


def format_duration(seconds: float | None) -> str:
    """Format seconds as H:MM:SS / M:SS, or 'Unavailable'."""
    if seconds is None:
        return "Unavailable"
    total = int(round(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def detect_duration_seconds(data: bytes, filename: str) -> float | None:
    """Return duration for WAV files using the stdlib; None for other containers.

    Duration for MP3/M4A/MP4/WEBM would need an extra dependency, so it is reported
    as unavailable rather than estimated.
    """
    if get_extension(filename) != ".wav":
        return None
    try:
        with wave.open(io.BytesIO(data)) as wav:
            frames, rate = wav.getnframes(), wav.getframerate()
            return frames / rate if rate else None
    except (wave.Error, EOFError):
        return None


@contextlib.contextmanager
def temporary_audio_file(data: bytes, suffix: str) -> Iterator[Path]:
    """Write audio to a temp file for the Gemini SDK, and always delete it afterwards."""
    fd, name = tempfile.mkstemp(prefix="pdai_", suffix=suffix)
    path = Path(name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        yield path
    finally:
        with contextlib.suppress(OSError):
            path.unlink()
