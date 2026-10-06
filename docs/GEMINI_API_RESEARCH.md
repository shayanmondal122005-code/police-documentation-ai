# Gemini API Research

**Date of research:** 2026-10-06
**Method:** Official Google documentation fetched on the research date, plus direct
inspection of the installed official SDK (`google-genai` 2.28.0) type definitions
for exact parameter names. No third-party tutorials were used as authority.

> **Honesty note.** No live Gemini API key was available while this MVP was built.
> The Gemini integration was written against the documentation and SDK types and
> is covered by mock-based tests. It has **not** been exercised against the live
> service, and Hindi/Bhojpuri accuracy has **not** been measured. Treat the first
> real run as a verification step.

## Official documentation references

| Topic | URL |
|---|---|
| Models | https://ai.google.dev/gemini-api/docs/models |
| Gemini 3.8 Flash | https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash |
| Gemini 3.5 Transcribe (model page) | https://ai.google.dev/gemini-api/docs/models/gemini-3.5-transcribe |
| Audio transcription guide | https://ai.google.dev/gemini-api/docs/generate-content/transcribe |
| Audio understanding | https://ai.google.dev/gemini-api/docs/audio |
| Structured output | https://ai.google.dev/gemini-api/docs/structured-output |
| Files API | https://ai.google.dev/gemini-api/docs/files |
| Rate limits | https://ai.google.dev/gemini-api/docs/rate-limits |
| Pricing / free tier / data use | https://ai.google.dev/gemini-api/docs/pricing |
| API keys / authentication | https://ai.google.dev/gemini-api/docs/api-key |
| Interactions API | https://ai.google.dev/gemini-api/docs/interactions |

## Selected models

| Role | Model ID | Status |
|---|---|---|
| Default transcription (prompted) | `gemini-3.8-flash` | Stable, free tier |
| Optional transcription (dedicated ASR) | `gemini-3.5-transcribe` | Stable, free tier |
| Reasoning / structured report | `gemini-3.8-flash` | Stable, free tier |

All three are overridable via environment variables (see `config.py`).

### Why

* **`gemini-3.8-flash`** accepts audio input, supports structured (JSON-schema)
  output and thinking, has a 1,048,576-token context window, is marked *Stable*,
  and has a free tier. It accepts free-text instructions, which is what lets the
  transcription prompt carry the Hindi / Bhojpuri / code-switching rules from the
  product specification.
* **`gemini-3.5-transcribe`** is Google's dedicated speech-to-text model with
  diarization (up to 8 speakers) and word-level timestamps. It is offered as an
  *optional* engine, **not** the default, because (a) Bhojpuri is not in its
  documented language list, and (b) the documented call takes only audio plus an
  `audio_transcription_config`; there is no documented way to pass the
  Hindi/Bhojpuri instructions to it.
* **`gemini-3.1-pro-preview`** is listed as a higher-capability reasoning model
  but is a *preview* model with **no free tier**. It can be selected with
  `GEMINI_REPORT_MODEL=gemini-3.1-pro-preview` by users on a paid tier.

## Supported capabilities (documented)

* **Audio input formats:** WAV, MP3, AIFF, AAC, OGG, FLAC, MPEG, M4A, L16, Opus,
  ALAW, MULAW, WebM. **`.mp4` is not in the documented audio MIME list.** This
  MVP sends `.mp4` as `video/mp4` (Gemini documents video input and processes the
  audio track), but audio extraction from MP4 is **unverified** by this project.
  If an MP4 fails, convert it to WAV/MP3/M4A first.
* **Audio length:** up to 9.5 hours per prompt for general audio understanding
  (32 tokens per second of audio).
* **Dedicated ASR length:** 1 hour per request; **30 minutes** when diarization
  or word timestamps are enabled.
* **Hindi:** supported by `gemini-3.5-transcribe` (`hi-IN`) among 85+ locales.
* **Code-switching:** documented for `gemini-3.5-transcribe`.
* **Diarization:** `gemini-3.5-transcribe` only, via
  `GenerateContentConfig(audio_transcription_config=AudioTranscriptionConfig(diarization=True))`.
  Speaker labels look like `spk_1`. Attribution for 3+ speakers is documented as
  *experimental*. Incompatible with custom vocabulary and SMART mode.
* **Word timestamps:** `gemini-3.5-transcribe` only, via
  `AudioTranscriptionConfig(word_timestamp=True)`. Returned as per-word
  `start_offset` / `end_offset` in `Part.audio_transcription.words`. The docs warn
  this **degrades transcription accuracy**.
* **Prompted timestamps:** general audio understanding can reference `MM:SS`
  positions. These are model-generated text, not ASR-aligned offsets.
* **Transcription modes:** `VERBATIM` (default; required for timestamps and
  diarization) and `SMART` (removes disfluencies, reformats; incompatible with
  timestamps/diarization). This MVP always uses `VERBATIM`.
* **Python SDK:** `google-genai` (import `from google import genai`). The legacy
  `google-generativeai` package is deprecated and is not used.
* **Authentication:** API key. The SDK reads `GEMINI_API_KEY` or `GOOGLE_API_KEY`
  (the latter takes precedence if both are set). This MVP passes the key
  explicitly from `GEMINI_API_KEY` to avoid ambiguity.
* **Large files:** Files API (`client.files.upload`, `.get`, `.delete`), max 2 GB
  per file, 20 GB per project, files retained 48 h unless deleted. This MVP
  deletes each uploaded file right after use.
* **Structured output:** `GenerateContentConfig(response_mime_type="application/json",
  response_json_schema=<Pydantic>.model_json_schema())`, then validate with
  `Model.model_validate_json(response.text)`. Not every JSON Schema feature is
  supported and very large/deeply nested schemas may be rejected.
* **API styles:** the newer Interactions API (`client.interactions.create`) is
  recommended by Google for new projects, but `generate_content` "remains fully
  supported" and is the only documented route for `audio_transcription_config`
  in this SDK. This MVP uses `generate_content`.

## Unavailable / unverified capabilities

* **Bhojpuri is not in the documented language list** of any Gemini audio
  model. Hindi is. Bhojpuri speech may be transcribed as Hindi-like text, partly
  garbled, or normalised toward standard Hindi. The prompt asks the model not to
  do this, but the instruction cannot guarantee it. **Treat all Bhojpuri
  transcription as unverified until a human who speaks Bhojpuri reviews it.**
* **Hindi + Bhojpuri mixing:** no documentation. Treated as unsupported/unverified.
* **Diarization / ASR timestamps in the prompted engine:** not provided as
  structured data. Speaker labels and times from the prompted engine are
  model-generated text and are labelled `model-reported (unverified)`.
* **Voice-based identification:** not supported, and explicitly forbidden by this
  product's rules. Speaker labels are anonymous (`spk_1`, `Speaker 1`).
* **Word timestamps and diarization together with custom vocabulary:**
  incompatible (not used by this MVP).
* **Instruction following in `gemini-3.5-transcribe`:** the documented request
  contains audio only; no instruction channel is documented, so the
  Hindi/Bhojpuri prompt is **not applied** in the dedicated ASR engine.
* **Verbatim guarantee:** neither engine guarantees a verbatim transcript.
  Even in `VERBATIM` mode, models may normalise spellings or drop false starts.

## Free-tier limitations

* `gemini-3.8-flash` and `gemini-3.5-transcribe`: input/output **free of charge**
  on the free tier. `gemini-3.1-pro-preview`: **no free tier**.
* Exact RPM / TPM / RPD figures are **not published on the rate-limits page**;
  they are per-project and visible in Google AI Studio. Exceeding any of the
  three dimensions returns a rate-limit error (HTTP 429), which the app reports
  as a human-readable "rate limit" message.
* **Data use (critical for this product):** on the free tier, submitted content
  is documented as **used to improve Google products**. On the paid tier it is
  not. Police recordings should **never** be sent through a free-tier key outside
  of testing with non-sensitive audio.
* Interactions are stored by default in the Interactions API (1 day free /
  55 days paid); this MVP uses `generate_content` and deletes uploaded files.

## Important API limitations

* Dedicated ASR with diarization or word timestamps: 30-minute cap.
* Word timestamps reduce ASR accuracy (documented).
* Diarization for 3+ speakers is experimental (documented).
* Streamlit's default upload cap is 200 MB; this MVP sets it explicitly in
  `.streamlit/config.toml` and enforces `MAX_UPLOAD_MB` in code.
* Model output is probabilistic. JSON-schema output guarantees shape, not truth.

## Implications for this MVP

1. **Two transcription engines behind one `Transcriber` interface.**
   *Prompted* (`gemini-3.8-flash`, default) carries the Hindi/Bhojpuri rules;
   *Dedicated ASR* (`gemini-3.5-transcribe`) gives real diarization and word
   offsets. The officer chooses in the UI.
2. **Timestamps and speakers are never invented.** The transcript records where
   they came from (`none`, `asr_word_offsets`, `model_reported`). If the source
   is `none`, the report generator forces every report timestamp to `null` after
   model output, regardless of what the model returned.
3. **Dedicated-ASR timestamps cap audio at 30 minutes.** The UI warns, and the
   engine can be run without timestamps for longer recordings.
4. **Bhojpuri risk is surfaced, not hidden.** The report always carries a
   language-uncertainty note, and the README documents the limitation.
5. **Privacy:** audio and transcript text are sent to Google. A free-tier key
   permits Google to use that data to improve its products. The UI and README say
   so prominently. Production use needs a paid/enterprise agreement and review.
6. **Verification layer:** every extracted statement/fact/allegation carries a
   source quote; code (not the model) checks the quote exists in the transcript
   and flags it otherwise.
