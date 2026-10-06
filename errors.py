"""Exceptions whose messages are safe to show to an officer.

Every class here carries a human-readable `user_message`. Internal details
(stack traces, raw API responses) must never be placed in these messages.
"""

from __future__ import annotations


class UserFacingError(Exception):
    """Base class for errors that can be displayed verbatim in the UI."""

    def __init__(self, user_message: str) -> None:
        super().__init__(user_message)
        self.user_message = user_message


class ConfigurationError(UserFacingError):
    """Missing or invalid configuration (e.g. no API key)."""


class UnsupportedFileError(UserFacingError):
    """File extension or container is not supported."""


class EmptyFileError(UserFacingError):
    """Uploaded file contains no data."""


class FileTooLargeError(UserFacingError):
    """Uploaded file exceeds the configured limit."""


class NoSpeechError(UserFacingError):
    """No intelligible speech was found in the recording."""


class TranscriptionError(UserFacingError):
    """Transcription failed."""


class ReportGenerationError(UserFacingError):
    """Report generation failed."""


class ReportValidationError(ReportGenerationError):
    """Model output could not be validated against the report schema."""


class ExportError(UserFacingError):
    """Export failed."""
