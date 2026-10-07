"""Report generation through Groq strict JSON output or a local fictional mock."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Protocol

import groq

from config import REPORT_MAX_COMPLETION_TOKENS, REPORT_MODEL, GroqModels
from errors import ReportGenerationError
from utils.groq import close_client, create_client, request_error_kind, strict_schema, translate_error, validate_models

MOCK_ANALYSIS_PATH = Path(__file__).resolve().parent.parent / "sample_data" / "mock_model_report.json"
logger = logging.getLogger(__name__)


class ReportModelClient(Protocol):
    """Anything that can turn (system instruction, prompt, JSON schema) into a JSON string."""

    def generate_json(self, system_instruction: str, prompt: str, schema: dict[str, Any]) -> str: ...


class GroqReportClient:
    """Strict schema output with bounded JSON-mode recovery and local validation."""

    def __init__(self, client: groq.Groq | None = None, model: str = REPORT_MODEL) -> None:
        validate_models(GroqModels(report=model))
        self._client = client
        self._model = model
        self.actual_model: str | None = None
        self.actual_format: str | None = None
        self._use_json_object = False

    def _request(self, client: groq.Groq, system_instruction: str, prompt: str, schema: dict[str, Any]) -> Any:
        wire_schema = strict_schema(schema)
        if self._use_json_object:
            # JSON mode guarantees syntax only. The same schema is included in
            # the prompt, and report_generator still validates with Pydantic.
            system_instruction += (
                "\n\nReturn only one JSON object matching this schema. Use empty arrays, "
                "null unavailable values and unknown attribution; never invent facts to fill fields.\n"
                + json.dumps(wire_schema, ensure_ascii=False, separators=(",", ":"))
            )
            response_format = {"type": "json_object"}
        else:
            response_format = {"type": "json_schema", "json_schema": {
                "name": "police_field_report", "strict": True, "schema": wire_schema,
            }}
        return client.chat.completions.create(
            model=self._model,
            messages=[{"role": "system", "content": system_instruction}, {"role": "user", "content": prompt}],
            reasoning_effort="low",
            max_completion_tokens=REPORT_MAX_COMPLETION_TOKENS,
            response_format=response_format,
        )

    def generate_json(self, system_instruction: str, prompt: str, schema: dict[str, Any]) -> str:
        client = self._client
        try:
            client = client or create_client()
            try:
                response = self._request(client, system_instruction, prompt, schema)
            except groq.APIStatusError as exc:
                if self._use_json_object or exc.status_code != 400 or request_error_kind(exc) != "report_format":
                    raise
                # Never read or reuse failed_generation from the error body.
                # Retry once on the same model/provider, only for format errors.
                logger.warning("Groq rejected structured report output; trying JSON mode once (HTTP 400).")
                self._use_json_object = True
                response = self._request(client, system_instruction, prompt, schema)
            if not response.choices:
                raise ReportGenerationError("Groq returned no report. Please try again.")
            choice = response.choices[0]
            if choice.finish_reason == "length":
                raise ReportGenerationError("Groq's report reached its output limit. Use a shorter recording; no partial report was accepted.")
            if choice.finish_reason == "content_filter" or getattr(choice.message, "refusal", None):
                raise ReportGenerationError("Groq declined to generate this report. No report was accepted.")
            if choice.finish_reason != "stop":
                raise ReportGenerationError("Groq did not complete the report. No partial report was accepted.")
            if not choice.message.content:
                raise ReportGenerationError("Groq returned no report text. Please try again.")
            self.actual_model = self._model
            self.actual_format = "json_object" if self._use_json_object else "json_schema"
            return choice.message.content
        except Exception as exc:  # noqa: BLE001 - translated to a safe message
            raise translate_error(exc, ReportGenerationError, "Groq report generation") from exc
        finally:
            if self._client is None and client is not None:
                close_client(client)


class MockReportClient:
    """Returns a canned analysis that matches the mock transcript. No network, no API key."""

    def __init__(self, path: Path = MOCK_ANALYSIS_PATH) -> None:
        self._path = path

    def generate_json(self, system_instruction: str, prompt: str, schema: dict[str, Any]) -> str:
        return self._path.read_text(encoding="utf-8")
