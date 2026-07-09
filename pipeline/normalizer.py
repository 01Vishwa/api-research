"""
Normalizer — applies verified corrections to an AppRecord.
Keeps enum parsing + correction logic in one place.
"""

from __future__ import annotations

from models.schema import (
    AccessModel,
    APIType,
    AppRecord,
    APISurface,
    AuthMethod,
    Blocker,
)


def _to_auth_list(values: list[str]) -> list[AuthMethod]:
    result = []
    for v in values:
        try:
            result.append(AuthMethod(v))
        except ValueError:
            pass
    return result or [AuthMethod.UNKNOWN]


def _to_api_list(values: list[str]) -> list[APIType]:
    result = []
    for v in values:
        try:
            result.append(APIType(v))
        except ValueError:
            pass
    return result or [APIType.UNKNOWN]


def normalize_record(record: AppRecord, derived: dict) -> AppRecord:
    """
    Apply verifier's derived values to the record where they differ.
    Only applies high-confidence corrections (confidence ≥ 0.6).
    """
    conf = float(derived.get("confidence", 0.0))

    if conf < 0.6:
        return record  # Don't apply low-confidence corrections

    updated = record.model_copy(deep=True)

    if "auth_methods" in derived and derived["auth_methods"]:
        updated.auth_methods = _to_auth_list(derived["auth_methods"])

    if "access_model" in derived and derived["access_model"] not in ("unknown", None):
        try:
            updated.access_model = AccessModel(derived["access_model"])
        except ValueError:
            pass

    if "api_types" in derived and derived["api_types"]:
        old_surface = updated.api_surface
        updated.api_surface = APISurface(
            types=_to_api_list(derived["api_types"]),
            breadth=old_surface.breadth,
            webhooks=old_surface.webhooks,
            rate_limits_documented=old_surface.rate_limits_documented,
            notes=old_surface.notes,
        )

    if "buildable_today" in derived and derived["buildable_today"] is not None:
        updated.buildable_today = bool(derived["buildable_today"])

    if "blocker" in derived and derived["blocker"] not in ("unknown", None):
        try:
            updated.blocker = Blocker(derived["blocker"])
        except ValueError:
            pass

    return updated
