# Police Documentation AI

A Streamlit MVP that turns an uploaded recording into an **AI-generated draft** field-interaction report for officer review. It now uses **Groq for both transcription and report generation**. Gemini credentials are no longer used.

**Not production-ready for real police evidence.** Reports require review against the original recording. This app has no authentication, access control or forensic chain-of-custody system.

## Quick start

Python 3.12 is tested.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python run_app.py
```

On Windows, activate with `.venv\Scripts\activate` and copy `.env.example` to `.env` using your editor or file manager.

Open http://localhost:8501. Without a key, select **Try fictional demo**, then **Generate demo report**. The demo uses a canned Hindi/Bhojpuri transcript, ignores the silent placeholder audio and makes no API calls.

## Groq Console setup

1. Create a server-side API key at [Groq Console → API Keys](https://console.groq.com/keys).
2. Set `GROQ_API_KEY` in your local `.env` or in Streamlit Cloud's **Settings → Secrets**.
3. Ensure your Groq project permits `whisper-large-v3` and `openai/gpt-oss-120b` in its [model permissions](https://console.groq.com/settings/project/limits).
4. Choose **Upload audio → Groq Whisper — multilingual transcription**.
5. Open **Groq connection and model settings** and click **Test Groq connection**. This tests a short structured request to the report model; it does not test transcription.
6. Upload a short, non-sensitive WAV/MP3 and generate, review and export the draft.

For Streamlit Secrets:

```toml
GROQ_API_KEY = "your-groq-key-here"
```

For a local `.env`:

```dotenv
GROQ_API_KEY=your-groq-key-here
```

Keep the real key out of Git and chat messages. `.env` and `.streamlit/secrets.toml` are git-ignored. Keys are read server-side and are never copied into report/session data or exports.

Optional model overrides, supported in either environment variables or Streamlit Secrets:

| Setting | Default | Supported alternative |
|---|---|---|
| `GROQ_TRANSCRIPTION_MODEL` | `whisper-large-v3` | `whisper-large-v3-turbo` |
| `GROQ_REPORT_MODEL` | `openai/gpt-oss-120b` | `openai/gpt-oss-20b` |

Environment values take priority. Reboot after changing deployment settings. Incompatible models are rejected before an API call; GPT-OSS is selected because it supports strict JSON-schema output.

## Deploy on Streamlit Community Cloud

Select this GitHub repository, branch **main**, entry point **app.py**, and Python **3.12**. Add `GROQ_API_KEY` in the app's server-side Secrets settings, save and reboot. The Groq version is also available on **app-readiness**.

Existing `GEMINI_API_KEY` and `GEMINI_*` model settings can be removed. They do not enable Groq. Dependencies now install the official `groq` SDK instead of `google-genai`.

The local server binds to localhost. Streamlit telemetry is disabled. Shared deployments are suitable only for non-sensitive demos while authentication and production controls are absent.

## Models and audio limits

Models and request formats were checked against official Groq documentation on **2026-10-07**; see [Groq API research](docs/GROQ_API_RESEARCH.md).

| Stage | API/model | Behavior |
|---|---|---|
| Transcription | Groq `/audio/transcriptions`, `whisper-large-v3` | Original-language text and optional real segment offsets |
| Report | Groq `/chat/completions`, `openai/gpt-oss-120b` | Strict JSON schema, Pydantic validation and conservative guardrails |
| Offline demo | Local fixtures | Fictional transcript and report; no API requests |

- Maximum direct upload: **25 MB**, with a conservative 25,000,000-byte app cap. No automatic compression, chunking or URL uploads.
- Formats: MP3, WAV, M4A, MP4, MPEG, MPGA, WEBM, FLAC, OGG. Only the first audio track is transcribed for files with multiple tracks.
- WAV duration is detected locally; other containers show **Unavailable** rather than an estimate.
- **Segment timestamps** can be disabled. Offsets are supplied by speech recognition, not guessed by the report model.
- **Speaker diarization is unavailable** in this Whisper integration. Attribution stays unknown unless the transcript explicitly identifies it.
- The multilingual transcription endpoint is used, not the English translation endpoint. Language detection stays automatic for mixed speech.
- A compact Hindi spelling/context hint is supplied. Whisper prompts guide context/style; they cannot enforce chat-style instructions or guarantee verbatim Bhojpuri.
- Hindi/Bhojpuri accuracy has not been measured. Review names, numbers, dialect wording and mixed-language speech against the audio.

Groq offers a free plan with request, token and audio quotas. Exact limits belong to the organization and can be checked in [Groq Console → Limits](https://console.groq.com/settings/limits). Large transcripts may exceed free-plan token limits despite fitting the upload size cap. Start with a short recording.

**No live API key was available during implementation.** Automated tests use a mock HTTP transport with the actual Groq SDK; live transcription and language accuracy still need verification with your deployment/key.

## Review and exports

The six tabs show **REPORT**, **TRANSCRIPT**, **TIMELINE**, **STATEMENTS**, **EVIDENCE** and **METADATA**. Metadata records the transcription and report models. The complete raw transcript is shown and downloadable independently of the report.

Edit the report and officer correction notes, then confirm review to enable Markdown, TXT, DOCX and PDF downloads. Editing again clears the confirmation. A failed new request preserves the previous report and edits. **Start new report** resets the recording, metadata, report and review in the current session.

DOCX supports Hindi text. PDF export is refused for Devanagari because the current ReportLab implementation cannot shape it correctly; use DOCX instead.

## Accuracy and integrity

After generation, code validates the schema, verifies source quotes against the raw transcript, removes unsupported timestamps, preserves allegation attribution, reclassifies hedged facts as belief/hearsay and flags guilt/lying/confession wording. Malformed analysis gets one guided retry, then a controlled failure. Partial, empty or refused Groq reports are not accepted. These are conservative heuristics, not substitutes for human review.

SHA-256 and the recording ID identify uploaded bytes and help detect later changes. They do not prove who recorded the file, when it was recorded or whether it was changed before upload.

## Privacy and failures

Audio is uploaded directly to Groq for transcription; transcript text is sent to Groq for report generation. No Google Files API or remote file store is used by this app. Temporary local audio files are removed on success and failure. Uploads and results remain in the active Streamlit session until reset/session end.

Groq documents limited retention for reliability/abuse monitoring and configurable data controls, including Zero Data Retention. Review [Groq's data policy](https://console.groq.com/docs/your-data) and your organization settings before sensitive use. The provider switch does not make this MVP production-ready.

The SDK retries transient failures twice with backoff. UI errors identify transcription versus report generation and include HTTP status; app logs record only exception type/status, never raw API responses or recording text. API keys are not logged or exported.

- **401:** check `GROQ_API_KEY`.
- **403/404:** check project model permissions and configured IDs.
- **429:** check Console quotas, wait before retrying, or use shorter audio.
- **400/413/422:** check format, request size/model settings; test a small valid WAV/MP3.
- **5xx/timeouts:** retry later with short audio. Moving providers cannot guarantee service availability.

## Development and Docker

```bash
pip install -r requirements-dev.txt
python -m pytest
```

Tests exercise the offline UI, officer review and exports, raw transcript/timestamp handling, actual SDK multipart/strict JSON request formats through a mock transport, retry/error paths, secret resolution and cleanup. They never call a live provider. GitHub Actions runs the suite on pushes and pull requests.

```bash
docker build -t police-documentation-ai .
docker run --rm -p 127.0.0.1:8501:8501 --env-file .env police-documentation-ai
```

Omit `--env-file .env` for the demo. Docker uses a non-root user and excludes secrets, recordings and tests. Docker has not been built in the development environment.

| Directory | Responsibility |
|---|---|
| `transcription/` | Transcript interface, Groq Whisper and local mock |
| `documentation/` | Report schemas, Groq client, validation, guardrails and rendering |
| `integrity/` | Recording ID, SHA-256 and processing metadata |
| `export/` | Markdown, TXT, DOCX and PDF exports |
| `ui/` | Streamlit presentation and server-side settings |
| `utils/` | Audio validation/temp files and Groq helpers |
| `sample_data/` | Explicitly fictional offline fixtures |
| `tests/` | Regression suite without live API credentials |
