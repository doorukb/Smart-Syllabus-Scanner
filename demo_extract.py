from __future__ import annotations
import argparse
import datetime
import functools
import json
import os
import re
import sys
from typing import Any, Final

from anthropic import Anthropic
from anthropic.types import Message
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

try:
    from dotenv import load_dotenv
except ImportError:  # python-dotenv not installed; set ANTHROPIC_API_KEY directly
    load_dotenv = lambda: None  # noqa: E731

# Pinned snapshot ID (weights fixed for this ID). See README for aliases / upgrades. Feel free to change it into a different model for your own use
MODEL_ID: Final[str] = "claude-haiku-4-5-20251001"

DEFAULT_MAX_CHARS: Final[int] = 50_000
MAX_OUTPUT_TOKENS: Final[int] = 4096

REPAIR_USER_PROMPT: Final[str] = (
    "Your previous reply was not valid JSON for the syllabus extraction schema, "
    "or it included markdown/code fences or prose outside JSON. "
    "Reply again with ONLY a single JSON object (no markdown, no ``` fences, no commentary) "
    "that strictly matches the schema you were given."
)

class GradingWeight(BaseModel):
    model_config = ConfigDict(extra="forbid")

    component: str = Field(..., description="Name of graded component, e.g. Midterm, Homework")
    percent: float = Field(..., description="Weight as percent (0-100)")

class ImportantDate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(..., description="Human-readable label, e.g. Final exam")
    date_iso: str | None = Field(
        default=None,
        description="ISO-8601 date if known, else null",
    )
    raw_text: str = Field(
        default="",
        description="Verbatim date/time phrase from syllabus if ISO not inferable",
    )

    @field_validator("date_iso", mode="before")
    @classmethod
    def _validate_iso_date(cls, v: object) -> object:
        if v is None or v == "":
            return v
        try:
            datetime.date.fromisoformat(str(v))
        except ValueError as exc:
            raise ValueError(
                f"date_iso must be a valid ISO-8601 date (YYYY-MM-DD), got: {v!r}"
            ) from exc
        return v

class SyllabusExtraction(BaseModel):
    """Structured syllabus extraction target (Option A: prompt + JSON parse + Pydantic)."""

    model_config = ConfigDict(extra="forbid")

    course_code: str | None = Field(default=None, description="Course code if present, e.g. CS 101")
    instructor_email: str | None = Field(default=None, description="Primary instructor email if present")
    grading_weights: list[GradingWeight] = Field(default_factory=list)
    important_dates: list[ImportantDate] = Field(default_factory=list)
    policy_bullets: list[str] = Field(default_factory=list)

def _debug_stderr(debug: bool, message: str) -> None:
    if debug:
        print(message, file=sys.stderr)

def _strip_json_fences(text: str) -> str:
    """Remove optional ``` / ```json wrappers without treating inner content as logs."""
    stripped = text.strip()
    m = re.match(r"^```(?:json)?\s*\n?(.*?)\n?```\s*$", stripped, flags=re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return stripped

def _message_text(message: Message) -> str:
    parts: list[str] = []
    for block in message.content:
        if getattr(block, "type", None) == "text":
            parts.append(getattr(block, "text", ""))
    return "".join(parts).strip()

def _parse_and_validate(raw_text: str) -> SyllabusExtraction:
    candidate = _strip_json_fences(raw_text)
    data: Any = json.loads(candidate)
    return SyllabusExtraction.model_validate(data)

@functools.lru_cache(maxsize=1)
def _build_system_prompt() -> str:
    schema = json.dumps(SyllabusExtraction.model_json_schema(), indent=2, ensure_ascii=False)
    return (
        "You extract syllabus information into structured data. "
        "You MUST respond with ONLY valid JSON — a single JSON object, no markdown, "
        "no code fences, no backticks, and no text before or after the JSON. "
        "Use null for unknown scalar fields; use empty arrays when no items apply. "
        "The JSON must conform to this JSON Schema (draft-like) for the object root:\n"
        f"{schema}\n"
        "Do not echo the source document; only output the JSON object."
    )

def _build_user_prompt(document: str) -> str:
    return (
        "Extract syllabus fields from the following document. "
        "Output ONLY the JSON object as specified in your instructions.\n\n"
        f"{document}"
    )

def _call_model(client: Anthropic, *, messages: list[dict[str, Any]], debug: bool) -> str:
    response = client.messages.create(
        model=MODEL_ID,
        max_tokens=MAX_OUTPUT_TOKENS,
        system=_build_system_prompt(),
        messages=messages,
    )
    _debug_stderr(debug, f"stop_reason={response.stop_reason}")
    return _message_text(response)


def extract_syllabus(document: str, *, client: Anthropic, debug: bool) -> SyllabusExtraction:
    """One API call plus at most one repair retry after JSON/Pydantic failure."""
    user_content = _build_user_prompt(document)
    messages: list[dict[str, Any]] = [{"role": "user", "content": user_content}]

    raw = _call_model(client, messages=messages, debug=debug)
    try:
        return _parse_and_validate(raw)
    except (json.JSONDecodeError, ValidationError) as first_err:
        _debug_stderr(debug, f"first_parse_failed={type(first_err).__name__}")

    messages.append({"role": "assistant", "content": raw})
    messages.append({"role": "user", "content": REPAIR_USER_PROMPT})
    raw_repair = _call_model(client, messages=messages, debug=debug)
    try:
        return _parse_and_validate(raw_repair)
    except (json.JSONDecodeError, ValidationError) as second_err:
        raise RuntimeError(
            "Model output could not be parsed as JSON matching the schema after one repair attempt."
        ) from second_err

def _read_input_text(args: argparse.Namespace) -> str:
    if args.file is not None:
        path = os.path.abspath(args.file)
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    return sys.stdin.read()

def _truncate(text: str, max_chars: int, *, debug: bool) -> str:
    if len(text) <= max_chars:
        return text
    _debug_stderr(debug, f"input_truncated length={len(text)} max_chars={max_chars}")
    return text[:max_chars]

def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Extract syllabus-oriented JSON from text using Anthropic Messages API.",
    )
    p.add_argument(
        "--file",
        "-f",
        metavar="PATH",
        help="Read syllabus text from this UTF-8 file (default: stdin)",
    )
    p.add_argument(
        "--max-chars",
        type=int,
        default=DEFAULT_MAX_CHARS,
        metavar="N",
        help=f"Maximum characters of input to send (default: {DEFAULT_MAX_CHARS})",
    )
    p.add_argument(
        "--debug",
        action="store_true",
        help="Print minimal diagnostics to stderr (never prints full user document or model JSON).",
    )
    return p.parse_args(argv)

def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    load_dotenv()  # no-op if .env absent or python-dotenv not installed
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key or not str(api_key).strip():
        print(
            "error: ANTHROPIC_API_KEY is not set or is empty. "
            "Set it in your environment (do not commit secrets).",
            file=sys.stderr,
        )
        return 2

    try:
        text = _read_input_text(args)
    except OSError as e:
        print(f"error: could not read input: {e}", file=sys.stderr)
        return 2

    text = _truncate(text, args.max_chars, debug=args.debug)
    if not text.strip():
        print("error: input is empty after trimming.", file=sys.stderr)
        return 2

    client = Anthropic(api_key=api_key)
    try:
        result = extract_syllabus(text, client=client, debug=args.debug)
    except Exception as e:
        print(f"error: extraction failed: {e}", file=sys.stderr)
        return 1

    print(json.dumps(result.model_dump(mode="json"), indent=2, ensure_ascii=False))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
