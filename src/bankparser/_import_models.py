"""Import assessment output models, separate from the canonical parse schema."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from bankparser._import_duplicates import DuplicateCandidate
from bankparser._import_policy import DestinationAccount, ImportPolicy
from bankparser.models import ValidationResult

ReadinessStatus = Literal["ready", "review", "not-ready"]


@dataclass(frozen=True, slots=True)
class ImportReason:
    """Structured blocker/review reason; indices are zero-based source positions."""

    code: str
    severity: Literal["review", "block"]
    path: str
    transaction_indices: tuple[int, ...]
    message: str
    source_code: str | None = None


@dataclass(frozen=True, slots=True)
class ImportAssessment:
    """Version-1 destination assessment; canonical parse schema remains separate."""

    assessment_schema_version: str
    status: ReadinessStatus
    policy: ImportPolicy
    destination: DestinationAccount | None
    account_origin: Literal["source", "destination-context", "missing"]
    result_fingerprint: str
    recorded_validation_status: str
    validation: ValidationResult
    reasons: tuple[ImportReason, ...]
    duplicate_candidates: tuple[DuplicateCandidate, ...]
