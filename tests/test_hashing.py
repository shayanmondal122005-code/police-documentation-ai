import hashlib
import io
from datetime import datetime, timezone

from integrity.hashing import build_integrity, make_recording_id, sha256_stream


def test_sha256_matches_known_vector():
    digest, size = sha256_stream(io.BytesIO(b"abc"))
    assert digest == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    assert size == 3


def test_streaming_hash_equals_one_shot_hash_across_chunk_boundaries():
    data = bytes(range(256)) * 1000
    digest, size = sha256_stream(io.BytesIO(data), chunk_size=997)
    assert digest == hashlib.sha256(data).hexdigest()
    assert size == len(data)


def test_empty_stream_hashes_to_empty_digest():
    digest, size = sha256_stream(io.BytesIO(b""))
    assert digest == hashlib.sha256(b"").hexdigest()
    assert size == 0


def test_stream_is_rewound_after_hashing():
    stream = io.BytesIO(b"hello")
    sha256_stream(stream)
    assert stream.read() == b"hello"


def test_recording_id_is_deterministic_and_hash_derived():
    digest = hashlib.sha256(b"x").hexdigest()
    assert make_recording_id(digest) == make_recording_id(digest)
    assert make_recording_id(digest) == f"REC-{digest[:12].upper()}"
    assert make_recording_id(digest) != make_recording_id(hashlib.sha256(b"y").hexdigest())


def test_build_integrity_populates_all_fields():
    moment = datetime(2026, 3, 4, 5, 6, 7, tzinfo=timezone.utc)
    info = build_integrity(io.BytesIO(b"abc"), "a.wav", now=moment)
    assert info.filename == "a.wav"
    assert info.size_bytes == 3
    assert info.sha256.startswith("ba7816bf")
    assert info.processed_at == "2026-03-04 05:06:07 UTC"
    assert info.recording_id == "REC-BA7816BF8F01"
