from __future__ import annotations
from pydantic import BaseModel
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