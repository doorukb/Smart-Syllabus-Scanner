from __future__ import annotations
import argparse
import datetime
import functools
import json
import os
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
TOOL_NAME: Final[str] = "submit_syllabus_extraction"

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
    """Structured syllabus extraction target returned via native tool use."""

    model_config = ConfigDict(extra="forbid")

    course_code: str | None = Field(default=None, description="Course code if present, e.g. CS 101")
    instructor_email: str | None = Field(default=None, description="Primary instructor email if present")
    grading_weights: list[GradingWeight] = Field(default_factory=list)
    important_dates: list[ImportantDate] = Field(default_factory=list)
    policy_bullets: list[str] = Field(default_factory=list)

def _debug_stderr(debug: bool, message: str) -> None:
    if debug:
        print(message, file=sys.stderr)

def _detect_input_type(path: str) -> str:
    """Returns the lowercase extension (e.g. '.pdf') or '.txt' for everything else."""
    ext = os.path.splitext(path)[1].lower()
    return ext if ext in _EXT_MAP else ".txt"


def _binary_blocks_from_file(path: str) -> list[ContentBlock]:
    """Read a PDF or image and return a single API content block."""
    ext = os.path.splitext(path)[1].lower()
    block_type, media_type = _EXT_MAP[ext]
    with open(path, "rb") as f:
        raw = f.read()
    if len(raw) > MAX_BINARY_BYTES:
        raise ValueError(
            f"File is {len(raw) // (1024 * 1024)} MB — "
            f"exceeds the {MAX_BINARY_BYTES // (1024 * 1024)} MB cap. "
            "Reduce the file size or extract the text manually first."
        )
    b64 = base64.standard_b64encode(raw).decode("ascii")
    return [
        {
            "type": block_type,
            "source": {"type": "base64", "media_type": media_type, "data": b64},
        }
    ]

@functools.lru_cache(maxsize=1)
def _build_tool() -> dict[str, Any]:
    return {
        "name": TOOL_NAME,
        "description": "Submit structured syllabus fields extracted from the document.",
        "input_schema": SyllabusExtraction.model_json_schema(),
    }

@functools.lru_cache(maxsize=1)
def _build_system_prompt() -> str:
    return (
        "You extract syllabus information into structured data. "
        "Use null for unknown scalar fields; use empty arrays when no items apply. "
        "Do not echo the source document."
    )

def _build_user_prompt(document: str) -> str:
    return (
        "Extract syllabus fields from the following document.\n\n"
        f"{document}"
    )

def _call_model(client: Anthropic, *, messages: list[dict[str, Any]], debug: bool) -> Message:
    response = client.messages.create(
        model=MODEL_ID,
        max_tokens=MAX_OUTPUT_TOKENS,
        system=_build_system_prompt(),
        messages=messages,
        tools=[_build_tool()],
        tool_choice={"type": "tool", "name": TOOL_NAME},
    )
    _debug_stderr(debug, f"stop_reason={response.stop_reason}")
    return response

def _parse_tool_use(message: Message) -> SyllabusExtraction:
    for block in message.content:
        if getattr(block, "type", None) == "tool_use" and block.name == TOOL_NAME:
            return SyllabusExtraction.model_validate(block.input)
    raise RuntimeError(
        f"Model did not return a {TOOL_NAME!r} tool_use block."
    )

def extract_syllabus(document: str, *, client: Anthropic, debug: bool) -> SyllabusExtraction:
    """Single API call; model returns structured data via tool_use."""
    messages: list[dict[str, Any]] = [{"role": "user", "content": _build_user_prompt(document)}]
    response = _call_model(client, messages=messages, debug=debug)
    try:
        return _parse_tool_use(response)
    except ValidationError as exc:
        raise RuntimeError(
            "Tool input did not pass Pydantic validation."
        ) from exc

def _read_input(args: argparse.Namespace, *, debug: bool) -> list[ContentBlock]:
    """Return content blocks representing the user's document."""
    if args.file is None:
        return [{"type": "text", "text": sys.stdin.read()}]

    path = os.path.abspath(args.file)
    input_type = _detect_input_type(path)

    if input_type == ".txt":
        with open(path, encoding="utf-8", errors="replace") as f:
            return [{"type": "text", "text": f.read()}]

    if args.max_chars != DEFAULT_MAX_CHARS:
        _debug_stderr(debug, "warning: --max-chars has no effect on PDF/image input")

    _debug_stderr(debug, f"input_type={input_type[1:]} path={path}")
    return _binary_blocks_from_file(path)

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
