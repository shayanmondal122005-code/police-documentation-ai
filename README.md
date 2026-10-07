# Police Documentation AI

A police officer uploads an audio recording of a field interaction. The app transcribes it,
extracts a structured, evidence-aware analysis, and produces a **draft** *Police Field
Interaction Report* that the officer reviews, edits and exports.

> **AI-GENERATED DRAFT — REQUIRES OFFICER REVIEW**
> Output is never an official police record. This is an MVP and is **not production-ready for
> real police evidence** (see [Security limitations](#security-limitations)).

This is not a generic meeting summariser. It keeps *facts*, *allegations*, *beliefs*, *hearsay*
and *uncertainty* distinct, never invents timestamps or speakers, and links every extracted
item back to a transcript quote that the code verifies.

## Architecture

```
Streamlit UI (app.py, ui/)
   ↓
Audio upload → validation → streaming SHA-256 → Recording ID        (utils/audio.py, integrity/)
   ↓
Gemini transcription  (or Mock)                                      (transcription/)
   ↓
Structured transcript  (raw text kept separately; times/speakers only if real)
   ↓
Gemini report generation  (JSON-schema structured output)            (documentation/)
   ↓
Pydantic validation (+ one guided retry) → deterministic guardrails
   ↓
Officer review / edit (Markdown + Officer Review section)
   ↓
Export: Markdown · TXT · DOCX · PDF (Latin text only)                (export/)
```

| Path | Responsibility |
|---|---|
| `app.py`, `ui/` | Streamlit interface and session state |
| `pipeline.py` | Orchestrates upload → transcript → report (no Streamlit imports) |
| `config.py` | Model names, limits, formats, timeouts, notices |
| `transcription/` | `Transcriber` interface, Gemini engines, mock engine |
| `documentation/` | Pydantic schemas, report generator, guardrails, Markdown renderer, model clients |
| `prompts/` | Transcription and analysis prompts (single source each) |
| `integrity/` | SHA-256 hashing and deterministic Recording ID |
| `export/` | Markdown/TXT/DOCX/PDF export |
| `docs/GEMINI_API_RESEARCH.md` | Dated research on the current Gemini API and its limits |

## Installation

Requires Python 3.11+.

```bash
python -m venv .venv
```

Activate the environment:

* **Windows (PowerShell):** `.venv\Scripts\Activate.ps1`
* **Windows (cmd):** `.venv\Scripts\activate.bat`
* **Linux / macOS:** `source .venv/bin/activate`

```bash
pip install -r requirements.txt
```

## Environment setup

Copy `.env.example` to `.env` and set your key. `.env` is git-ignored and must never be committed.

```
GEMINI_API_KEY=your-key-here
```

Optional overrides (defaults are in `config.py`): `GEMINI_TRANSCRIPTION_MODEL`,
`GEMINI_ASR_MODEL`, `GEMINI_REPORT_MODEL`.

## Gemini API setup

1. Create a key in [Google AI Studio](https://aistudio.google.com/apikey).
2. Put it in `.env` as `GEMINI_API_KEY`. The app uses the official `google-genai` SDK
   (`from google import genai`) and passes the key explicitly.
3. Models (verified against Google's documentation on 2026-10-06; see
   [`docs/GEMINI_API_RESEARCH.md`](docs/GEMINI_API_RESEARCH.md)):
   * Prompted transcription and report generation: `gemini-3.8-flash`
   * Optional dedicated ASR (speaker labels, word timestamps): `gemini-3.5-transcribe`

> **Not yet verified live.** The Gemini integration was built from the official documentation and
> SDK types and is tested against a mocked Gemini layer. It has not been run against the live
> service, and Hindi/Bhojpuri accuracy has not been measured. Do a first run with a harmless
> recording before relying on it.

No API key? Choose the **Mock** engine in the UI to run the whole pipeline locally on a fictional
transcript. Nothing is sent anywhere.

## Running

```bash
python run_app.py
```

The server binds to `localhost` only and Streamlit telemetry is disabled (`.streamlit/config.toml`).

Open http://localhost:8501. Without a key, the app starts in **Try fictional demo** mode:
click **Generate demo report** to explore all six report tabs with the built-in sample.
No recording is needed and this mode makes no Gemini requests. To process your own
recording, choose **Upload audio** and configure a Gemini key.

Edit the report and correction notes, then confirm that you have reviewed the draft
to enable report downloads. Editing again resets that confirmation. A failed new
generation preserves the previous report and your edits. **Start new report** clears
the recording, report, review and case details from the current app session.

### Streamlit Community Cloud (demo hosting)

Select this repository, branch and `app.py` as the entry point. Configure Python 3.12.
For Gemini, add this in the app's server-side **Secrets** settings:

```toml
GEMINI_API_KEY = "your-key-here"
```

Locally, the same entry can go in `.streamlit/secrets.toml` (git-ignored). An environment
or `.env` key takes priority. The app never stores the key in report/session data.
Without a key, the fictional demo remains usable. Any shared deployment is for
non-sensitive demos only: this MVP still has no authentication or access control.

### Docker (local demo)

```bash
docker build -t police-documentation-ai .
docker run --rm -p 127.0.0.1:8501:8501 --env-file .env police-documentation-ai
```

Omit `--env-file .env` for the offline demo. The container runs as a non-root user,
excludes secrets and recordings from its build context, and includes a health check.
The Docker image has not been built in the development environment; the Python app
and its health endpoint have been tested directly.

## Testing

```bash
pip install -r requirements-dev.txt
python -m pytest
```

Tests never call the real Gemini API; the Gemini layer is mocked.
The suite includes Streamlit AppTest coverage for demo generation, review/download
state, reset, and preserving an edited report after a failed request. GitHub Actions
runs these checks on pushes and pull requests.

## Supported audio formats

MP3, WAV, M4A, MP4, MPEG, WEBM. Maximum upload: 200 MB (`config.MAX_UPLOAD_MB`).
Duration is displayed for WAV only; other containers show "Unavailable" rather than a guess.
`.mp4` is sent to Gemini as `video/mp4`, and extraction of the audio track is not verified by this
project; convert to WAV/MP3/M4A if it fails.

## Transcription engines

| Engine | Model | Strengths | Limits |
|---|---|---|---|
| **Prompted** (default) | `gemini-3.8-flash` | Carries the Hindi/Bhojpuri/code-switching instructions | Speaker labels and times are model-written text, shown as *model-reported (unverified)* |
| **Dedicated ASR** | `gemini-3.5-transcribe` | Real diarization (≤ 8 speakers) and word offsets | **Bhojpuri not in its language list; accepts no instructions**; ≤ 30 min with timestamps/speakers; timestamps lower accuracy |
| **Mock** | none | Local demo, no key | Fictional transcript only |

## Hindi / Bhojpuri considerations

* Hindi is a documented language of Gemini's speech model. **Bhojpuri is not documented as
  supported**, and Hindi–Bhojpuri mixing is not documented at all.
* The prompt tells the model to keep Bhojpuri as spoken, not translate, not "standardise" it into
  Hindi, and to mark unclear words. A prompt cannot guarantee this. Expect some Bhojpuri to be
  rendered Hindi-like or mis-heard.
* Every report carries a language-uncertainty note. **Have a Bhojpuri speaker check the raw
  transcript** before the report is relied on.
* The raw transcript is shown and downloadable (`transcript.txt`) separately from the report and
  is never replaced by a summary. Neither engine guarantees a strictly verbatim transcript.

## How accuracy rules are enforced

Prompts alone are not trusted. After the model answers, code:

* validates the JSON against Pydantic schemas (one guided retry, then a controlled error);
* **removes every timestamp** if the transcript has none, and never invents speakers;
* **verifies each source quote** against the raw transcript and flags unverifiable ones;
* **re-classifies hedged "facts"** (e.g. *मुझे लगता है कि राहुल वहाँ था* / *I think…* / hearsay
  markers) as belief or hearsay, and always prints allegations as "*X alleged that …*";
* flags guilt/lying/confession language for the officer.

These are conservative heuristics, not a substitute for human review.

## Privacy

* When Gemini is used, **audio and transcript text are sent to Google's Gemini API**.
* On the Gemini API **free tier, Google may use submitted content to improve its products**; the
  paid tier does not. Do not process real case material with a free-tier key.
* Recordings are never stored permanently. They exist in memory and in a temporary file only for
  the duration of processing; the temp file is deleted afterwards, as is the copy uploaded to
  Google's Files API (otherwise retained 48 h).
* No analytics, telemetry or advertising. Transcript contents and secrets are never logged; logs
  contain only exception class names.
* Exports never include API keys, secrets or debug data.

## Security limitations

This MVP is **not** production-ready for real police evidence. Production would need, among other
things: security review, legal review, departmental approval, privacy/data-processing review,
authentication, authorization, encryption (in transit and at rest), audit logging, retention
policies, secure deployment, and chain-of-custody controls. There is no login, no access control
and no audit trail here; anyone who can reach the app can use it.

PDF export is refused for reports containing Devanagari because ReportLab cannot shape Hindi
correctly; use DOCX.

## SHA-256 limitation

The SHA-256 hash and Recording ID identify the uploaded file and help detect later changes to it.
They are an **integrity identifier, not chain of custody**. They do not prove who recorded the
audio, when, on which device, or that the file was unaltered before upload.

## Replacing Gemini with Whisper / faster-whisper

Report generation depends only on `TranscriptResult` (`transcription/base.py`). To swap engines:

1. Create `transcription/whisper_transcriber.py` with a class that subclasses `Transcriber` and
   implements `transcribe(audio_path, mime_type, options) -> TranscriptResult`. Fill `segments`
   with real `start_time`/`end_time` from Whisper, leave `speaker` as `None` unless you add
   diarization, and set `timestamp_source="asr_word_offsets"` only for genuine offsets.
2. Register it in `pipeline.build_engines` and add a label in `config.ENGINE_LABELS`.

Nothing in `documentation/`, `export/` or `ui/` needs to change. For fully local processing also
replace `GeminiReportClient` (`documentation/clients.py`) with any class that implements
`generate_json(system_instruction, prompt, schema) -> str`.

## Future architecture

Authentication and role-based access · encrypted storage · case management · timestamp-linked
playback (the schema already carries `start_time`/`end_time`/`quote` per item, ready to seek the
player) · mandatory human review workflow · tamper-evident audit trails · secure deployment ·
departmental system integrations · retention and disposal policies.
