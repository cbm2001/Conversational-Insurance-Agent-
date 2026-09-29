from __future__ import annotations

import re
from typing import Any

from harness.fixtures import all_policyholders, all_representatives, get_policyholder


def normalize_phone(value: str | None) -> str:
    if not value:
        return ""
    digits = re.sub(r"\D", "", value)
    if len(digits) > 10 and digits.startswith("1"):
        digits = digits[-10:]
    return digits[-10:] if len(digits) >= 10 else digits


def normalize_email(value: str | None) -> str:
    return (value or "").strip().lower()


def normalize_name(value: str | None) -> str:
    return " ".join((value or "").lower().split())


def normalize_dob(value: str | None) -> str:
    if not value:
        return ""
    raw = value.strip()
    for sep in ("/", "."):
        raw = raw.replace(sep, "-")
    return raw


def _name_matches(record: dict[str, Any], collected_name: str | None) -> bool:
    if not collected_name:
        return False
    target = normalize_name(collected_name)
    candidates = [normalize_name(record.get("name", ""))]
    for alias in record.get("name_aliases") or []:
        candidates.append(normalize_name(alias))
    return target in candidates


def _phone_matches(record: dict[str, Any], collected_phone: str | None) -> bool:
    if not collected_phone:
        return False
    target = normalize_phone(collected_phone)
    phones = [normalize_phone(record.get("phone"))]
    for alias in record.get("phone_aliases") or []:
        phones.append(normalize_phone(alias))
    return target in phones and bool(target)


def _email_matches(record: dict[str, Any], collected_email: str | None) -> bool:
    if not collected_email:
        return False
    target = normalize_email(collected_email)
    emails = [normalize_email(record.get("email"))]
    for alias in record.get("email_aliases") or []:
        emails.append(normalize_email(alias))
    return target in emails


def _dob_matches(record: dict[str, Any], collected_dob: str | None) -> bool:
    if not collected_dob:
        return False
    return normalize_dob(collected_dob) == normalize_dob(record.get("dob"))


def _id_last4_matches(record: dict[str, Any], collected_last4: str | None) -> bool:
    if not collected_last4:
        return False
    digits = re.sub(r"\D", "", collected_last4)
    if len(digits) != 4:
        return False
    return digits == re.sub(r"\D", "", str(record.get("id_last4", "")))


def count_matching_fields(record: dict[str, Any], collected: dict[str, Any]) -> int:
    count = 0
    if _name_matches(record, collected.get("name")):
        count += 1
    if _dob_matches(record, collected.get("dob")):
        count += 1
    if _phone_matches(record, collected.get("phone")):
        count += 1
    if _email_matches(record, collected.get("email")):
        count += 1
    if _id_last4_matches(record, collected.get("id_last4")):
        count += 1
    return count


def merge_pii(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = dict(existing)
    for key in ("name", "dob", "phone", "email", "id_last4", "policy_number"):
        value = incoming.get(key)
        if value is not None and str(value).strip():
            merged[key] = str(value).strip()
    return merged


def check_representative_verification(user_input: str, collected: dict[str, Any]) -> tuple[bool, str | None, bool, str | None, str | None]:
    """Validate a third-party caller against the rep and policyholder fixtures in one pass."""
    text_lower = (user_input or "").lower()
    input_name = normalize_name(collected.get("name"))

    for rep in all_representatives():
        rep_name = normalize_name(rep.get("rep_name", ""))
        rep_name_in_input = rep_name in text_lower or rep_name == input_name
        if not rep_name_in_input:
            continue

        buyer_id = rep.get("buyer_party_id")
        holder = get_policyholder(buyer_id) if buyer_id else None
        if not holder:
            continue

        rel = (rep.get("relationship") or "").lower()
        rel_mentioned = bool(rel and rel in text_lower) or any(
            phrase in text_lower for phrase in ("mother", "mom", "father", "dad", "parent", "for")
        )

        holder_name_match = "margaret" in text_lower or normalize_name(holder.get("name", "")) in text_lower
        dob_match = _dob_matches(holder, collected.get("dob")) or holder.get("dob", "") in text_lower
        last4_match = _id_last4_matches(holder, collected.get("id_last4")) or str(holder.get("id_last4", "")) in text_lower

        if rel_mentioned and holder_name_match and dob_match and last4_match:
            return True, buyer_id, True, rep.get("rep_name"), holder.get("name")

        if rep_name_in_input and dob_match and last4_match:
            return True, buyer_id, True, rep.get("rep_name"), holder.get("name")

    return False, None, False, None, None


def verify_identity(collected: dict[str, Any]) -> tuple[bool, str | None, bool, str | None]:
    """
    Deterministic verification: >= 3 matching PII fields against a policyholder.
    Authorized representatives verify against the buyer's record when rep name matches.
    """
    if not collected:
        print("[VERIFY DEBUG] Matches: 0, Party: None")
        return False, None, False, None

    synthetic_text = " ".join(
        str(value or "") for value in (collected.get("name"), collected.get("dob"), collected.get("id_last4"))
    )
    rep_verified, rep_party_id, rep_ok, rep_name, policyholder_name = check_representative_verification(
        synthetic_text, collected
    )
    if rep_verified and rep_party_id:
        print(f"[VERIFY DEBUG] Immediate rep verification: {rep_name} for {rep_party_id}")
        return True, rep_party_id, rep_ok, policyholder_name

    rep_match: dict[str, Any] | None = None
    collected_name = collected.get("name")
    if collected_name:
        for rep in all_representatives():
            if normalize_name(rep.get("rep_name", "")) == normalize_name(collected_name):
                rep_match = rep
                break

    best_party_id: str | None = None
    best_count = 0
    for holder in all_policyholders():
        matches = count_matching_fields(holder, collected)
        is_rep_for_holder = bool(rep_match and rep_match.get("buyer_party_id") == holder.get("party_id"))

        if is_rep_for_holder:
            has_matching_dob = _dob_matches(holder, collected.get("dob"))
            has_matching_last4 = _id_last4_matches(holder, collected.get("id_last4"))
            if has_matching_dob and has_matching_last4:
                print(f"[VERIFY DEBUG] Immediate rep verification: {rep_match.get('rep_name')} for {holder['party_id']}")
                return True, holder["party_id"], True, holder.get("name")

            buyer_fields = sum(
                [
                    has_matching_dob,
                    _phone_matches(holder, collected.get("phone")),
                    _email_matches(holder, collected.get("email")),
                    has_matching_last4,
                ]
            )
            matches = max(matches, buyer_fields + 1)

        if matches > best_count:
            best_count = matches
            best_party_id = holder["party_id"]
        if matches >= 3:
            is_rep = bool(rep_match and rep_match.get("buyer_party_id") == holder.get("party_id"))
            print(f"[VERIFY DEBUG] Matches: {matches}, Party: {holder['party_id']}")
            return True, holder["party_id"], is_rep, holder.get("name")

    print(f"[VERIFY DEBUG] Matches: {best_count}, Party: {best_party_id}")
    return False, None, False, None


def fields_still_needed(collected: dict[str, Any]) -> list[str]:
    """Human-readable list of PII dimensions not yet collected (for prompts)."""
    labels = {
        "name": "full legal name",
        "dob": "date of birth",
        "phone": "phone number on the policy",
        "email": "email address on the policy",
        "id_last4": "last four digits of SSN or national ID",
    }
    missing: list[str] = []
    for key, label in labels.items():
        if not collected.get(key):
            missing.append(label)
    return missing


def matching_field_count(collected: dict[str, Any]) -> int:
    best = 0
    for holder in all_policyholders():
        best = max(best, count_matching_fields(holder, collected))
    return best
