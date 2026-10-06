"""Model clients for report generation: a protocol, the Gemini client and a local mock."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from google import genai
from google.genai import types

from config import REPORT_MODEL, REPORT_TEMPERATURE
from errors import ReportGenerationError
from utils.gemini import create_client, simplify_schema, translate_error

MOCK_ANALYSIS_PATH = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "mock_model_report.json"


class ReportModelClient(Protocol):
    """Anything that can turn (system instruction, prompt, JSON schema) into a JSON string."""

    def generate_json(self, system_instruction: str, prompt: str, schema: dict[str, Any]) -> str: ...


class GeminiReportClient:
    """Gemini structured-output client (`response_json_schema`)."""

    def __init__(self, client: genai.Client | None = None, model: str = REPORT_MODEL) -> None:
        self._client = client
        self._model = model

    def generate_json(self, system_instruction: str, prompt: str, schema: dict[str, Any]) -> str:
        try:
            client = self._client or create_client()
            response = client.models.generate_content(
                model=self._model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=REPORT_TEMPERATURE,
                    response_mime_type="application/json",
                    response_json_schema=simplify_schema(schema),
                ),
            )
            return response.text or ""
        except Exception as exc:  # noqa: BLE001 - translated to a safe message
            raise translate_error(exc, ReportGenerationError, "Report generation") from exc


class MockReportClient:
    """Returns a canned analysis that matches the mock transcript. No network, no API key."""

    def __init__(self, path: Path = MOCK_ANALYSIS_PATH) -> None:
        self._path = path

    def generate_json(self, system_instruction: str, prompt: str, schema: dict[str, Any]) -> str:
        return self._path.read_text(encoding="utf-8")
