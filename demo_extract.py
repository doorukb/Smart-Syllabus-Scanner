from __future__ import annotations
import argparse
import base64
import datetime
import functools
import json
import os
import sys
from typing import Any, Final, TypeAlias

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
MAX_BINARY_BYTES: Final[int] = 32 * 1024 * 1024
TOOL_NAME: Final[str] = "submit_syllabus_extraction"

ContentBlock: TypeAlias = dict[str, Any]

_EXT_MAP: Final[dict[str, tuple[str, str]]] = {
    ".pdf": ("document", "application/pdf"),
    ".jpg": ("image", "image/jpeg"),
    ".jpeg": ("image", "image/jpeg"),
    ".png": ("image", "image/png"),
}

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

# Structured syllabus extraction target returned via native tool use.
class SyllabusExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    course_code: str | None = Field(default=None, description="Course code if present, e.g. CS 101")
    instructor_email: str | None = Field(default=None, description="Primary instructor email if present")
    grading_weights: list[GradingWeight] = Field(default_factory=list)
    important_dates: list[ImportantDate] = Field(default_factory=list)
    policy_bullets: list[str] = Field(default_factory=list)

class ValidationWarning(BaseModel):
    model_config = ConfigDict(extra = 'forbid')
    field: str = Field(..., description="Which field the warning relates to, e.g. 'grading_weights")
    message: str = Field(..., description = "Plain-English description of the issue found")
    severity : str = Field(..., description = "'low', 'medium', or 'high'")

class ValidationResult(BaseModel) :
    model_config = ConfigDict(extra = 'forbid')
    warnings: list[ValidationWarning] = Field(default_factory=list)
    grading_sums_to_100 : bool = Field(..., description = "True if grading weights sum to 100%")
    grading_total : float = Field(..., description = "Actual sum of grading weights")
    date_summary: str | None = Field(default=None, description="Summary of important dates if present")
    policy_summary: str | None = Field(default=None, description="Summary of policies if present")
    course_summary: str | None = Field(default=None, description="Summary of course if present")
    instructor_summary: str | None = Field(default=None, description="Summary of instructor if present")
    course_code_summary: str | None = Field(default=None, description="Summary of course code if present")
    instructor_email_summary: str | None = Field(default=None, description="Summary of instructor email if present")
    grading_weights_summary: str | None = Field(default=None, description="Summary of grading weights if present")

def _debug_stderr(debug: bool, message: str) -> None:
    if debug:
        print(message, file=sys.stderr)

# returns the lowercase extension (e.g. '.pdf') or '.txt' for everything else
def _detect_input_type(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    return ext if ext in _EXT_MAP else ".txt"

# read a PDF or image and return a single API content block
def _binary_blocks_from_file(path: str) -> list[ContentBlock]:
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

@functions.lru_cache(maxsize = 1)
def _build_validation_tool() -> dict[str, Any]:
    schema = ValidationResult.model_json_schema()
    return {
        "name" : "report_validation",
        "description" : (
            "Report logial consistency issues found in extracted syllabus data."
            "Always call this tool even if no warnings are found."
        ),
        "input_schema" : schema,
    }

@functools.lru_cache(maxsize=1)
def _build_system_prompt() -> str:
    return (
        "You extract syllabus information into structured data. "
        "Use null for unknown scalar fields; use empty arrays when no items apply. "
        "Do not echo the source document."
    )

# Append the extraction instruction after the document block(s)
def _build_user_content(doc_blocks: list[ContentBlock]) -> list[ContentBlock]:
    instruction: ContentBlock = {
        "type": "text",
        "text": (
            "Extract all syllabus fields from the document above. "
            f"Call the {TOOL_NAME} tool with the structured data."
        ),
    }
    return doc_blocks + [instruction]

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

# single API call; model returns structured data via tool_use
def extract_syllabus(doc_blocks: list[ContentBlock], *, client: Anthropic, debug: bool) -> SyllabusExtraction:
    messages: list[dict[str, Any]] = [{"role": "user", "content": _build_user_content(doc_blocks)}]
    response = _call_model(client, messages=messages, debug=debug)
    try:
        return _parse_tool_use(response)
    except ValidationError as exc:
        raise RuntimeError(
            "Tool input did not pass Pydantic validation."
        ) from exc

# this is the second chained call, which checks the extracted data for logial inconsistencies and other contradictions
def validate_extraction(
    extraction : SyllabusExtraction,
    *,
    client : Anthropic,
    debug : tool,
) -> ValidationResult :
    payload = json.dumps(extraction.model_dump(mode = "json"), indent = 2, ensure_ascii = False)
    system = (
        "You are a syllabus data validator"
        "You will receive extracted syllabus data as JSON and must check it for logical issues."
        "Alyways call the report_validation tool, even when no issues were found."
    )
    user_content = (
        "Check this extracted syllabus data for logical inconsistencies:\n\n"
        f"{payload}\n\n"
        "Specifically:\n"
        "1. Do the grading_weights percentages sum to 100? Flag it if not.\n"
        "2. Are any important_dates logically inconsistent with each other "
        "(e.g. final before midterm, withdrawal deadline after final exam)?\n"
        "Report all issues via the report_validation tool."
    )
    response = client.messages.create(
        model = MODEL_ID,
        max_tokens = MAX_OUTPUT_TOKENS,
        system = system,
        tools = [_build_validation_tool()],
        tool_choice = {"type", "tool", "name", "report_validation"},
        messages = [{role : "user", "content" : user_content}],
    )
    _debug_stderr(debug, f"validation stop_reason={response.stop_reason}")

    for block in response.content:
        if getattr(block, "type", None) == "tool_use" and block.name == "report_validation" :
            return ValidationResult.model_validate(block.input)
    raise RuntimeError(
        "Validation call did not return a report_validation tool_use block. "
        f"Content types: {[getattr(b, 'type', '?') for b in response.content]}"
    )

# return content blocks representing the user's document
def _read_input(args: argparse.Namespace, *, debug: bool) -> list[ContentBlock]:
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

# truncate text blocks only; binary blocks (PDF, image) pass through unchanged
def _truncate_content(blocks: list[ContentBlock], max_chars: int, *, debug: bool) -> list[ContentBlock]:
    result = []
    for block in blocks:
        if block.get("type") == "text":
            text = block["text"]
            if len(text) > max_chars:
                _debug_stderr(debug, f"input_truncated length={len(text)} max_chars={max_chars}")
                block = {**block, "text": text[:max_chars]}
        result.append(block)
    return result

def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Extract syllabus-oriented JSON from text using Anthropic Messages API.",
    )
    p.add_argument(
        "--file", "-f",
        metavar="PATH",
        help="Syllabus file — .txt (default: stdin), .pdf, .jpg, or .png",
    )
    p.add_argument(
        "--max-chars",
        type=int,
        default=DEFAULT_MAX_CHARS,
        metavar="N",
        help=f"max characters for text input (default: {DEFAULT_MAX_CHARS}). No effect on PDF/image.",
    )
    p.add_argument(
        "--debug",
        action="store_true",
        help="Print minimal diagnostics to stderr (never prints full user document or model JSON).",
    )
    return p.parse_args(argv)

def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    load_dotenv()
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key or not str(api_key).strip():
        print("error: ANTHROPIC_API_KEY is not set.", file=sys.stderr)
        return 2
    try:
        blocks = _read_input(args, debug=args.debug)
    except (OSError, ValueError) as e:
        print(f"error: could not read input: {e}", file=sys.stderr)
        return 2
    blocks = _truncate_content(blocks, args.max_chars, debug=args.debug)
    # Guard against empty text input (binary blocks are never empty)
    if all(b.get("type") == "text" and not b["text"].strip() for b in blocks):
        print("error: input is empty after trimming.", file=sys.stderr)
        return 2

    client = Anthropic(api_key=api_key)
    try:
        result = extract_syllabus(blocks, client=client, debug=args.debug)
    except Exception as e:
        print(f"error: extraction failed: {e}", file=sys.stderr)
        return 1
    try : 
        validation = validate_extraction(result, cleint = client, debug = args.debug)
    except Exception as e:
        print(f"error: validation failed: {e}", file=sys.stderr)
        return 1
    output = {
        "extraction" : result.model_dump(mode = "json"),
        "validation" : validation.model_dump(mode = "json"),
    }
    print(json.dumps(output, indent = 2, ensure_ascii = False))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())