"""Streaming SHA-256 hashing and deterministic recording identifiers."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import BinaryIO

from pydantic import BaseModel

from config import HASH_CHUNK_BYTES


class RecordingIntegrity(BaseModel):
    """Integrity information captured immediately after upload."""

    recording_id: str
    filename: str
    size_bytes: int
    sha256: str
    processed_at: str


def sha256_stream(stream: BinaryIO, chunk_size: int = HASH_CHUNK_BYTES) -> tuple[str, int]:
    """Hash a binary stream in chunks; return (hex digest, bytes read).

    The stream is rewound to its start afterwards if it is seekable.
    """
    digest = hashlib.sha256()
    total = 0
    if stream.seekable():
        stream.seek(0)
    while chunk := stream.read(chunk_size):
        digest.update(chunk)
        total += len(chunk)
    if stream.seekable():
        stream.seek(0)
    return digest.hexdigest(), total


def make_recording_id(sha256_hex: str) -> str:
    """Deterministic ID derived from the hash: the same file always gets the same ID."""
    return f"REC-{sha256_hex[:12].upper()}"


def build_integrity(stream: BinaryIO, filename: str, now: datetime | None = None) -> RecordingIntegrity:
    """Compute hash, size and ID for an uploaded recording."""
    sha256_hex, size = sha256_stream(stream)
    moment = now or datetime.now(timezone.utc)
    return RecordingIntegrity(
        recording_id=make_recording_id(sha256_hex),
        filename=filename,
        size_bytes=size,
        sha256=sha256_hex,
        processed_at=moment.strftime("%Y-%m-%d %H:%M:%S UTC"),
    )
