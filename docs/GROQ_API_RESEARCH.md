# Groq API Research

Checked **2026-10-07** against official Groq documentation and the installed `groq` Python SDK **0.37.1**. This replaces the previous Gemini implementation and research.

## Official sources

| Topic | Source |
|---|---|
| API key creation | https://console.groq.com/keys |
| Speech transcription, formats, prompts and limits | https://console.groq.com/docs/speech-to-text |
| Whisper Large v3 | https://console.groq.com/docs/model/whisper-large-v3 |
| Supported models | https://console.groq.com/docs/models |
| GPT-OSS 120B | https://console.groq.com/docs/model/openai/gpt-oss-120b |
| Strict JSON-schema output | https://console.groq.com/docs/structured-outputs |
| Rate limits / free plan | https://console.groq.com/docs/rate-limits |
| Error codes | https://console.groq.com/docs/errors |
| Data controls / retention | https://console.groq.com/docs/your-data |
| Official Python SDK / retries | https://github.com/groq/groq-python |

## Selected integration

- **Audio:** `client.audio.transcriptions.create`, model `whisper-large-v3`, multipart file, `response_format="verbose_json"`, temperature 0, optional `timestamp_granularities=["segment"]`.
- **Report:** `client.chat.completions.create`, model `openai/gpt-oss-120b`, system/user messages and `response_format={"type":"json_schema","json_schema":{"name":"police_field_report","strict":true,"schema":...}}`.
- **Report budget:** `reasoning_effort="low"`, 4096 completion tokens. Truncated/empty/refused responses produce a controlled error; output is still Pydantic-validated and passed through guardrails.
- **Alternatives:** Whisper Large v3 Turbo for audio and GPT-OSS 20B for strict reports. The app restricts overrides to these verified pairs to avoid unsupported parameter/schema combinations.
- **Credentials:** `GROQ_API_KEY` in `.env`, environment or Streamlit Secrets. Model overrides follow the same server-side resolution. Environment takes priority; credentials are never stored in report/session data.

## Speech constraints

The free-plan audio size limit and direct attachment limit are 25 MB; the app uses a conservative 25,000,000-byte cap. The Developer plan's larger audio limit does not change this app's direct-attachment cap. No chunking, transcoding or URL hosting is implemented.

Supported formats in this app match the documented FLAC, MP3, MP4, MPEG, MPGA, M4A, OGG, WAV and WEBM types. Only the first audio track is transcribed. The transcription endpoint preserves source-language output; the translations endpoint translates to English and is deliberately unused.

Groq's Whisper integration does not provide diarization here. No speaker labels are requested or invented. Report attribution is checked conservatively and unknown speakers stay unknown. Timestamps describe segments, not word alignments. Invalid/reversed offsets are dropped. When segment text differs from the full transcript, the full text is kept and segment times are dropped to prevent lost text in analysis.

Whisper's `prompt` is a context/spelling hint, limited to 224 tokens, not an instruction-following chat prompt. The app supplies a short Hindi hint and lets language detection remain automatic for mixtures. Bhojpuri/mixed-language preservation is not guaranteed. Poor-confidence metadata is surfaced as review notes without rewriting speech.

## Strict schema adaptation

Groq requires all object properties in `required` and `additionalProperties: false` at every object node in strict mode. Optional values must remain nullable. `utils/groq.py` copies the Pydantic schema, closes objects recursively including `$defs`/`anyOf`, requires all fields and removes default/title annotations while preserving actual property names, refs, enums and null types.

The prompt instructs empty collections, null unavailable values and unknown attribution, avoiding invented content merely to fill required fields. Strict syntax does not guarantee factual accuracy, so the existing source-quote and allegation/uncertainty guardrails remain in force.

Recognized HTTP 400 schema/JSON-format failures get one compatibility retry using `response_format={"type":"json_object"}` on the same model. The full schema is included in the system instruction. This mode guarantees JSON syntax, not schema adherence: local Pydantic validation and conservative guardrails remain mandatory. A failed local validation gets the existing guided retry in JSON mode; invalid, partial or refused reports are never accepted. Provider `failed_generation` data is never used. Unknown 400 errors, token/context limits, account/access restrictions and content-policy failures do not trigger format recovery. The successful output mode is recorded in report metadata.

## Free-plan and failure behavior

The docs list free-plan quotas for both selected models. As checked, GPT-OSS 120B/20B have 8K TPM and Whisper models have 7.2K audio seconds/hour and 28.8K/day, with request/day limits as well. Exact organization limits can differ; Console is authoritative. A long report can exceed TPM even if the audio file fits 25 MB. The app does not claim unlimited free processing or automatically upgrade a plan.

The official SDK retries connection errors, 408/409/429 and server errors twice by default. The app explicitly keeps `max_retries=2` and sets a 180-second timeout with a 20-second connect timeout. It adds no infinite retry loop or quota-bypassing fallback. Safe errors preserve stage/status and fixed categories but never display raw response bodies, keys, audio or transcript text. Report request-size errors refer to text/token limits; only transcription errors suggest changing audio format.

## Data handling and verification limits

Audio is sent directly to Groq in a request; no remote Files API/store is used. Local temporary files and open upload handles are cleaned up on success and failure. A shared request-scoped SDK client is closed after processing.

Groq states that customer inference data is not retained by default, except features requiring retention or reliability/abuse monitoring; the latter may retain data for up to 30 days, subject to data controls and legal requirements. Zero Data Retention can be enabled in the organization settings. Usage metadata is retained. The app's notice now identifies Groq as the provider; this is not an approval for real police evidence.

**No local live key was available.** Tests run the actual SDK through an in-memory HTTP transport and verify requests, format recovery, validation/refusal handling, safe error classification, parsing, strict schema adaptation, cleanup, exports and the Streamlit review UI. The connection button generates and locally validates a fictional report with the real report schema only when clicked; a successful probe does not verify audio transcription. A live short recording and Hindi/Bhojpuri accuracy review remain necessary.
