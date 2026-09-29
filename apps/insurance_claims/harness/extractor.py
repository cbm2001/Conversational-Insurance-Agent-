from __future__ import annotations

import json
import re
from calendar import month_name
from pathlib import Path
from typing import Literal, Optional

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, Field

from harness.fixtures import all_policyholders, all_representatives
from harness.openai_client import create_llm_client, llm_model

_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_ENV_PATH)

_client: OpenAI | None = None


def get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = create_llm_client()
    return _client


class ExtractedPII(BaseModel):
    name: Optional[str] = None
    dob: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    id_last4: Optional[str] = None
    policy_number: Optional[str] = None


class ExtractedClaimHints(BaseModel):
    month: Optional[str] = Field(
        None,
        description="Month mentioned for the claim, e.g. January, Jan, 01",
    )
    case_type: Optional[str] = Field(
        None,
        description="Claim type keywords: healthcare, medical, dental, auto",
    )
    status: Optional[str] = Field(
        None,
        description="Status keywords such as denied, open, closed",
    )
    case_id: Optional[str] = Field(None, description="Explicit case ID if user mentions CL-####")
    free_text: Optional[str] = Field(
        None,
        description="Short summary of what the caller said about their claim intent",
    )


class TurnExtraction(BaseModel):
    is_in_scope: bool = Field(
        True,
        description="False for unrelated topics (coding, math, trivia, general AI questions)",
    )
    pii: ExtractedPII = Field(default_factory=ExtractedPII)
    claim_hints: ExtractedClaimHints = Field(default_factory=ExtractedClaimHints)
    user_done: bool = Field(
        False,
        description="True if the user indicates they have no more questions or are finished",
    )
    email_choice: Optional[Literal["send", "skip"]] = Field(
        None,
        description="When user responds to email summary offer: send or skip",
    )
    emotional_tone: Optional[str] = Field(
        None,
        description="frustration, anxiety, anger, confusion, refusal, or neutral",
    )


EXTRACTION_SYSTEM = """You extract structured facts from insurance customer service chat turns.
Rules:
- is_in_scope: false only when the user asks clearly unrelated questions (programming, math homework,
  trivia, politics unrelated to insurance, etc.). Insurance claims, verification, documents, status,
  empathy, and frustration about the process are IN SCOPE.
- pii: extract any identity fields the user provides (name, DOB, phone, email, last 4 of SSN/ID, policy number).
- claim_hints: extract claim-related hints even during identity verification (denied, healthcare, January, etc.).
- user_done: true if they say they are done, have no more questions, or want to wrap up.
- email_choice: set to send or skip only when they clearly accept or decline an email summary.
- emotional_tone: note frustration/refusal when present.
- Return only one valid JSON object matching the supplied schema. Use null for unknown optional values.
"""


def extract_turn(
    user_message: str,
    phase: str,
    recent_messages: list[dict],
) -> TurnExtraction:
    client = get_client()
    history_snippet = recent_messages[-6:] if recent_messages else []
    context_lines = "\n".join(f"{m['role']}: {m['content']}" for m in history_snippet)

    user_payload = f"""Current SOP phase: {phase}
Recent conversation:
{context_lines}

Latest user message:
{user_message}"""

    schema = json.dumps(TurnExtraction.model_json_schema(), separators=(",", ":"))
    completion = client.chat.completions.create(
        model=llm_model(),
        messages=[
            {"role": "system", "content": f"{EXTRACTION_SYSTEM}\nJSON schema: {schema}"},
            {"role": "user", "content": user_payload},
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )
    content = completion.choices[0].message.content or "{}"
    try:
        extracted = TurnExtraction.model_validate(json.loads(content))
    except (json.JSONDecodeError, TypeError, ValueError):
        extracted = TurnExtraction()

    return _merge_deterministic_extraction(extracted, user_message)


def _merge_deterministic_extraction(extracted: TurnExtraction, text: str) -> TurnExtraction:
    """Recover high-value fields when a local model returns valid but incomplete JSON."""
    pii = extracted.pii.model_dump(exclude_none=True)
    lowered = text.lower()

    known_names = [row.get("rep_name", "") for row in all_representatives()]
    for row in all_policyholders():
        known_names.append(row.get("name", ""))
        known_names.extend(row.get("name_aliases") or [])
    for name in known_names:
        if name and name.lower() in lowered:
            pii.setdefault("name", name)
            break

    patterns = {
        "dob": r"\b(?:dob|date of birth|birthdate|born)\s*(?:is|:)?\s*(\d{4}[-/.]\d{1,2}[-/.]\d{1,2})\b",
        "email": r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b",
        "id_last4": r"\b(?:ssn|social security|national id|id)\b.*?\b(\d{4})\b",
        "policy_number": r"\b(?:policy|policy number)\s*(?:is|:)?\s*([A-Z]{2,5}-\d{3,})\b",
    }
    for field, pattern in patterns.items():
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            pii.setdefault(field, match.group(1) if match.lastindex else match.group(0))

    hint_values = extracted.claim_hints.model_dump(exclude_none=True)
    month_re = re.compile(
        r"\b(?:in|during|for|from|since|around|before|after|on)\s+(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b",
        re.IGNORECASE,
    )
    month_match = month_re.search(text)
    if month_match:
        month_value = month_match.group(0).split()[-1].capitalize()
        hint_values.setdefault("month", month_value)
    else:
        for month in list(month_name)[1:]:
            if month.lower() == "may" and re.search(r"\bmay\s+i\b", lowered):
                continue
            if re.search(rf"\b{month}\b", text, re.IGNORECASE):
                if month.lower() == "may" and "claim" not in lowered and "case" not in lowered:
                    continue
                hint_values.setdefault("month", month)
                break
    for status in ("denied", "open", "closed", "pending", "approved"):
        if re.search(rf"\b{status}\b", lowered):
            hint_values.setdefault("status", status)
            break
    for case_type in ("healthcare", "medical", "dental", "auto"):
        if re.search(rf"\b{case_type}\b", lowered):
            hint_values.setdefault("case_type", case_type)
            break
    case_match = re.search(r"\bCL-\d{4}\b", text, re.IGNORECASE)
    if case_match:
        hint_values.setdefault("case_id", case_match.group(0).upper())

    if re.search(
        r"\b(?:that'?s|that is|i am)\s+(?:all|done)|\bno more questions\b|\bwrap(?:ping)? up\b",
        lowered,
    ):
        extracted.user_done = True
    if re.search(r"\b(?:yes|sure|please|yep|yeah)\b", lowered) and re.search(r"\b(?:send|email|summary)\b", lowered):
        extracted.email_choice = "send"
    elif re.search(r"\b(?:no|skip|don't|do not|fine|not needed|not necessary)\b", lowered) and re.search(
        r"\b(?:email|summary|send|fine)\b",
        lowered,
    ):
        extracted.email_choice = "skip"

    extracted.pii = ExtractedPII.model_validate(pii)
    extracted.claim_hints = ExtractedClaimHints.model_validate(hint_values)
    return extracted
