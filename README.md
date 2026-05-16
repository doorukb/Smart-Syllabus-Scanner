# Anthropic syllabus extraction (Option A)

Small Python CLI that sends syllabus-like text to the **Anthropic Messages API** and returns **validated JSON** using **Pydantic v2**. The model is instructed to emit **only JSON** (no markdown fences); the script parses JSON, validates with Pydantic, and **retries once** with a repair prompt if parsing or validation fails.

## Pinned model

This demo uses a **pinned snapshot** so behavior stays reproducible:

| Constant   | Value |
|-----------|--------|
| `MODEL_ID` in `demo_extract.py` | `claude-haiku-4-5-20251001` (Claude Haiku 4.5) |

Anthropic publishes dated snapshot IDs that map to fixed weights for the lifetime of that ID. For newer snapshots, see [Model IDs and versioning](https://platform.claude.com/docs/en/docs/about-claude/models) and update `MODEL_ID` accordingly.

## Setup

Requires **Python 3.10+**.

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Set your API key in the environment (do not commit it):

```bash
set ANTHROPIC_API_KEY=sk-ant-api03-...
```

On PowerShell:

```powershell
$env:ANTHROPIC_API_KEY = "sk-ant-api03-..."
```

## Run

**Stdin** (pipe or paste, then Ctrl+Z Enter on Windows):

```bash
type syllabus.txt | python demo_extract.py
```

**File**:

```bash
python demo_extract.py --file syllabus.txt
```

**Truncate long input** (default cap 50,000 characters):

```bash
python demo_extract.py --file syllabus.txt --max-chars 20000
```

**Minimal stderr diagnostics** (does not print your document or raw model output):

```bash
python demo_extract.py --file syllabus.txt --debug
```

Pretty-printed JSON is written to **stdout**.

## Environment

| Variable | Required | Purpose |
|----------|----------|---------|
| `ANTHROPIC_API_KEY` | Yes | Anthropic API key (read only from the environment). |

If `ANTHROPIC_API_KEY` is missing or empty, the program exits with code **2** and a short error on stderr.

## Limitations

- **LLMs can hallucinate or misread** tables, scans, and ambiguous wording; extracted grades, dates, and emails should be verified against the source syllabus.
- **Context limits** apply; very long documents should be split or summarized upstream. This script only applies a character cap (`--max-chars`), not token counting.
- **JSON-only prompting** reduces but does not eliminate formatting mistakes; a **single repair retry** handles many recoverable cases.
- **No server**: this is a standalone script (no FastAPI).

## Data handling / policy

**Disclaimer:** You are responsible for compliance with Anthropic’s [Commercial Terms](https://www.anthropic.com/legal/commercial-terms) and [Acceptable Use Policy](https://www.anthropic.com/legal/aup), your institution’s policies, and applicable privacy laws when sending syllabus or student-related text to third-party APIs. Do not send secrets or highly sensitive personal data you are not allowed to process externally.

The script is written to **avoid logging syllabus content** by default; `--debug` only emits minimal metadata (for example stop reason and error class names), not full prompts or responses.
