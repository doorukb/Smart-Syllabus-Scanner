from __future__ import annotations
from pydantic import BaseModel, Field
from demo_extract import SyllabusExtraction, ValidationResult, PolicyFlagResult

class ExtractionResponse(BaseModel):
    extraction: SyllabusExtraction
    validation: ValidationResult
    policy_flags: PolicyFlagResult


class HealthResponse(BaseModel):
    status: str
    version: str

class InfoResponse(BaseModel):
    name: str
    description: str
    endpoints: list[str]

class ChatMessage(BaseModel):
    role: str = Field(..., description="'user' or 'assistant'")
    content: str = Field(..., description="Message text")

class CalendarRequest(BaseModel):
    extraction: SyllabusExtraction

class ChatRequest(BaseModel):
    extraction: SyllabusExtraction
    history: list[ChatMessage] = Field(
        default_factory=list,
        description="Full conversation history so far, oldest first",
    )
    message: str = Field(..., description="The new user message to respond to")

class ChatResponse(BaseModel):
    answer: str = Field(..., description="Claude's answer")
    history: list[ChatMessage] = Field(
        description="Updated history including this turn, ready to send back next request",
    )
