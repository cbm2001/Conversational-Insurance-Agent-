from __future__ import annotations

from typing import Any

from harness.fixtures import get_claim, get_claims

MONTH_MAP = {
    "january": 1,
    "jan": 1,
    "february": 2,
    "feb": 2,
    "march": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "may": 5,
    "june": 6,
    "jun": 6,
    "july": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sep": 9,
    "sept": 9,
    "october": 10,
    "oct": 10,
    "november": 11,
    "nov": 11,
    "december": 12,
    "dec": 12,
}


def _month_from_hint(hint: str | None) -> int | None:
    if not hint:
        return None
    key = hint.strip().lower()
    if key.isdigit():
        num = int(key)
        if 1 <= num <= 12:
            return num
    return MONTH_MAP.get(key)


def _normalize_type(hint: str | None) -> str | None:
    if not hint:
        return None
    h = hint.lower()
    if "health" in h or "medical" in h:
        return "healthcare"
    if "dental" in h:
        return "dental"
    if "auto" in h or "car" in h:
        return "auto"
    return h


def _normalize_status(hint: str | None) -> str | None:
    if not hint:
        return None
    h = hint.lower()
    if "denied" in h or "denial" in h or "reject" in h:
        return "denied"
    if "open" in h or "progress" in h:
        return "open"
    if "closed" in h or "settled" in h or "paid" in h:
        return "closed"
    return h


def resolve_case(party_id: str, hints: dict[str, Any]) -> str | None:
    explicit = hints.get("case_id")
    if explicit:
        claim = get_claim(str(explicit))
        if claim and claim.get("party_id") == party_id:
            return claim["case_id"]

    claims = get_claims(party_id)
    if not claims:
        return None
    if len(claims) == 1:
        return claims[0]["case_id"]

    target_month = _month_from_hint(hints.get("month"))
    target_type = _normalize_type(hints.get("case_type"))
    target_status = _normalize_status(hints.get("status"))

    if len(claims) > 1 and target_type and not target_status and not target_month:
        return None
    if len(claims) > 1 and target_type and target_month and not target_status:
        return None

    strong_signal = bool(explicit) or bool(target_type and target_status) or bool(target_status and target_month)
    if not strong_signal:
        return None

    best_id: str | None = None
    best_score = -1
    tied_claims: list[str] = []
    for claim in claims:
        score = 0
        created = claim.get("created_at", "")
        if target_month and created:
            try:
                claim_month = int(created[5:7])
                if claim_month == target_month:
                    score += 3
                elif abs(claim_month - target_month) <= 1:
                    score += 1
            except ValueError:
                pass
        if target_type and claim.get("case_type") == target_type:
            score += 3
        if target_status and claim.get("status") == target_status:
            score += 3
        if score > best_score:
            best_score = score
            best_id = claim["case_id"]
            tied_claims = [claim["case_id"]]
        elif score == best_score and claim["case_id"] != best_id:
            tied_claims.append(claim["case_id"])

    if best_score <= 0:
        return None
    if len(tied_claims) > 1:
        return None
    return best_id


def merge_hints(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = dict(existing)
    for key, value in incoming.items():
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        merged[key] = value.strip() if isinstance(value, str) else value
    free_parts = [merged.get("free_text") or ""]
    for part in (incoming.get("free_text"),):
        if part and part not in free_parts:
            free_parts.append(part)
    merged["free_text"] = " ".join(p for p in free_parts if p).strip() or merged.get("free_text")
    return merged
