"""Pydantic data models — the contract between all pipeline stages."""

from __future__ import annotations

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


# ─── Enumerations ────────────────────────────────────────────────────────────

class AuthMethod(str, Enum):
    OAUTH2        = "OAuth2"
    API_KEY       = "API Key"
    BASIC         = "Basic Auth"
    BEARER_TOKEN  = "Bearer Token"
    HMAC          = "HMAC"
    JWT           = "JWT"
    NO_AUTH       = "No Auth"
    OTHER         = "Other"
    UNKNOWN       = "Unknown"


class AccessModel(str, Enum):
    SELF_SERVE     = "self-serve"
    PAID_PLAN      = "paid-plan-gated"
    ADMIN_APPROVAL = "admin-approval"
    PARTNER_GATED  = "partner-gated"
    CONTACT_SALES  = "contact-sales"
    UNKNOWN        = "unknown"


class APIType(str, Enum):
    REST      = "REST"
    GRAPHQL   = "GraphQL"
    SOAP      = "SOAP"
    GRPC      = "gRPC"
    WEBSOCKET = "WebSocket"
    NONE      = "None"
    UNKNOWN   = "Unknown"


class Breadth(str, Enum):
    BROAD    = "broad"
    MODERATE = "moderate"
    NARROW   = "narrow"
    NONE     = "none"
    UNKNOWN  = "unknown"


class Blocker(str, Enum):
    NONE                  = "none"
    PARTNER_APPROVAL      = "partner-approval-required"
    NO_PUBLIC_API         = "no-public-api"
    CONTACT_SALES         = "contact-sales-required"
    COMPLEX_OAUTH         = "complex-oauth-scopes"
    RATE_LIMIT_UNCLEAR    = "rate-limit-unclear"
    NO_DOCS               = "no-public-docs"
    ENTERPRISE_ONLY       = "enterprise-only"
    DEPRECATED            = "deprecated-api"
    ACCOUNT_REQUIRED      = "paid-account-required"
    UNKNOWN               = "unknown"


class VerificationStatus(str, Enum):
    CONFIRMED     = "confirmed"
    CORRECTED     = "corrected"
    NEEDS_HUMAN   = "needs-human"
    HUMAN_CHECKED = "human-checked"
    UNRESOLVED    = "unresolved"
    PENDING       = "pending"


# ─── Sub-models ──────────────────────────────────────────────────────────────

class APISurface(BaseModel):
    types: list[APIType] = Field(default_factory=list, description="API protocol types")
    breadth: Breadth = Breadth.UNKNOWN
    webhooks: bool = False
    rate_limits_documented: bool = False
    notes: str = ""


class MCPInfo(BaseModel):
    exists: bool = False
    link: Optional[str] = None
    official: bool = False  # official vs community


# ─── Primary App Record ───────────────────────────────────────────────────────

class AppRecord(BaseModel):
    """One row in the research dataset — schema is the contract between all agents."""

    id: int
    app: str
    category: str
    one_line: str = ""
    auth_methods: list[AuthMethod] = Field(default_factory=list)
    access_model: AccessModel = AccessModel.UNKNOWN
    api_surface: APISurface = Field(default_factory=APISurface)
    existing_mcp: MCPInfo = Field(default_factory=MCPInfo)
    developer_portal_url: Optional[str] = None
    buildable_today: Optional[bool] = None
    blocker: Blocker = Blocker.UNKNOWN
    evidence_url: str = ""
    secondary_evidence_urls: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    verification_status: VerificationStatus = VerificationStatus.PENDING
    verifier_notes: str = ""
    raw_llm_response: str = ""  # stored for debugging/audit

    class Config:
        use_enum_values = True


# ─── Verification Record ──────────────────────────────────────────────────────

class VerificationRecord(BaseModel):
    """Per-app verification outcome."""

    app: str
    field: str
    original_value: str
    verified_value: str
    changed: bool
    verifier_confidence: float
    source_url: str
    notes: str = ""


class VerificationLog(BaseModel):
    app: str
    status: VerificationStatus
    corrections: list[VerificationRecord] = Field(default_factory=list)
    verifier_notes: str = ""


# ─── Insights ─────────────────────────────────────────────────────────────────

class InsightStats(BaseModel):
    total_apps: int
    auth_distribution: dict[str, int]
    access_model_distribution: dict[str, int]
    api_type_distribution: dict[str, int]
    buildable_count: int
    not_buildable_count: int
    mcp_exists_count: int
    category_summary: dict  # category → {self_serve: N, gated: N, buildable: N}
    top_blockers: list[dict]
    easy_wins: list[str]      # self-serve + REST + buildable today
    hard_cases: list[str]     # contact-sales / partner-gated
    avg_confidence: float
