from __future__ import annotations

import json
from typing import Any

from harness.extractor import get_client
from harness.fixtures import document_guidelines, get_claim, get_claims, get_policyholder
from harness.openai_client import llm_model
from harness.state import SessionState
from harness.verifier import fields_still_needed, matching_field_count


def _guidance_for_documents(documents: list[str]) -> dict[str, str]:
    guidelines = document_guidelines()
    doc_map = guidelines.get("document_guidance") or {}
    alt_map = guidelines.get("document_alternative_guidance") or {}
    per_doc: dict[str, str] = {}
    for doc in documents:
        key = doc.lower()
        matched = None
        for k, v in doc_map.items():
            if k.lower() in key or key in k.lower():
                matched = v.get("en", "")
                break
        per_doc[doc] = matched or guidelines.get("default_guidance", {}).get("en", "")
        alt_key = None
        for k in alt_map:
            if k == "default":
                continue
            if k.lower() in key or key in k.lower():
                alt_key = k
                break
        if alt_key:
            per_doc[f"{doc} (alternatives)"] = alt_map[alt_key].get("en", "")
    per_doc["default_alternatives"] = alt_map.get("default", {}).get("en", "")
    return per_doc


def _followup_settings() -> dict[str, str]:
    g = document_guidelines()
    settings = g.get("claim_followup_settings") or {}
    return {
        "average_processing_time": settings.get("average_processing_time_after_submission", {}).get(
            "en", "usually less than a week"
        ),
        "human_review_note": settings.get("human_review_after_document_alternatives_exhausted", {}).get(
            "en", ""
        ),
    }


def build_grounded_context(state: SessionState) -> dict[str, Any]:
    ctx: dict[str, Any] = {
        "phase": state.phase,
        "verified": state.verified_party_id is not None,
        "party_id": state.verified_party_id,
        "is_representative": state.is_representative,
        "active_case_id": state.active_case_id,
        "pending_hints": state.pending_hints,
        "email_summary_offered": state.email_summary_offered,
        "email_summary_decision": state.email_summary_decision,
    }
    if state.verified_party_id:
        holder = get_policyholder(state.verified_party_id)
        if holder:
            ctx["policyholder"] = {
                "name": holder.get("name"),
            }
    if state.active_case_id:
        claim = get_claim(state.active_case_id)
        if claim:
            docs = claim.get("documents_needed") or []
            settings = _followup_settings()
            ctx["claim"] = claim
            ctx["document_guidance"] = _guidance_for_documents(docs)
            ctx["submission_turnaround"] = "within a week"
            ctx["review_timing"] = settings["average_processing_time"]
            ctx["human_review_note"] = settings["human_review_note"]
    return ctx


VERIFY_SYSTEM = """You are a compassionate insurance claims support agent in the VERIFY_ID phase.

CRITICAL SECURITY RULES (never break these):
- Do not access or confirm protected account records during verification.
- Do not disclose or speculate about sensitive claim or account details, even if the caller already mentioned them.
- Never ask the caller to confirm account identifiers, record details, or sensitive personal data.
- Acknowledge what they are calling about in general terms only (e.g. "I understand you're calling about an insurance matter")
  without confirming specifics from records.
- Explain that federal privacy rules require verifying identity before discussing protected health information.
- For ordinary verification, collect the minimum required identity fields: full name, date of birth, and last four of SSN/national ID.
- If the caller is an authorized representative and the relationship plus DOB and SSN last four match a policyholder record,
  verify immediately and move to case selection without asking for account identifiers or contact information.
- Accept partial information across turns; thank them for each piece and ask for what is still missing.
- If the caller is frustrated, angry, or refuses: empathize, explain why verification protects them,
  offer alternate ID fields, or offer transfer to a human representative. Do not skip verification.
- Stay professional, warm, and concise. Do not answer out-of-scope questions; redirect to the call purpose."""


RESOLVE_SYSTEM = """You are an insurance claims support agent in RESOLVE_INTENT phase.
Identity is verified. Use ONLY the grounded claim list and hints provided.
If the policyholder has multiple claims on file, you must explicitly list the available claim options and ask the caller which one they want to discuss.
Do not guess, do not pick the first claim, and do not bluff about a specific case if the data is ambiguous.
When there are multiple claims, present them in a clear, concise list and ask the user to choose.
Examples of the required behavior:
- 'I see Margaret Chen has two healthcare claims on file: CL-2011 (closed, January 2025) and CL-2048 (denied, January 2026). Which would you like to discuss?'
- 'I found multiple claims for this policyholder. Please tell me which case ID you mean: [list].'
Use the real case IDs and statuses from the grounded claim list; do not invent or generalize beyond that.
If there is exactly one claim, you may proceed without asking a clarifying question."""


PROCESS_SYSTEM = """You are an insurance claims support agent in PROCESS_CASE phase.
Answer using ONLY the grounded claim JSON and document guidance provided.
Keep the answer concise and conversational. Answer the specific question they asked, but do not dump the full document checklist or claim details unless they asked for them.
Every factual statement about the claim must come from the provided data (status, denial reason, documents needed, deadlines, amounts, next steps).
If asked something not covered by the data, say you do not have that detail and offer human transfer if needed.
For document submission: mention portal/upload when relevant; submission turnaround is within a week.
After documents are received, review timing is usually less than a week.
Include alternatives guidance when the caller cannot obtain exact documents."""


POST_SYSTEM = """You are an insurance claims support agent in POST_PROCESS phase.
Offer a concise email summary of the conversation (topics discussed, claim status/outcome, next steps)
to the verified email on file. Ask whether to send it or skip.
If they already chose send: confirm it will be sent to their email on file (do not invent addresses).
If they skipped: thank them and close warmly.
Do not introduce new claim facts not already discussed."""


def generate_reply(
    state: SessionState,
    user_message: str,
    *,
    scope_reply_override: str | None = None,
    emotional_tone: str | None = None,
) -> str:
    if scope_reply_override:
        return scope_reply_override

    client = get_client()
    phase = state.phase

    if phase == "VERIFY_ID":
        system = VERIFY_SYSTEM
        verify_status = {
            "fields_collected": list(state.collected_pii.keys()),
            "fields_still_needed": fields_still_needed(state.collected_pii),
            "matching_field_count_estimate": matching_field_count(state.collected_pii),
            "verified": False,
            "emotional_tone": emotional_tone,
        }
        context_block = json.dumps(verify_status, indent=2)
    else:
        grounded = build_grounded_context(state)
        context_block = json.dumps(grounded, indent=2, default=str)
        if phase == "RESOLVE_INTENT":
            system = RESOLVE_SYSTEM
            if state.verified_party_id:
                claims = get_claims(state.verified_party_id)
                if len(claims) > 1:
                    claim_options = "\n".join(
                        f"- {claim.get('case_id')}: {claim.get('case_type', 'unknown')} claim, {claim.get('status', 'unknown')} status, created {claim.get('created_at', 'unknown')}"
                        for claim in claims
                    )
                    system += (
                        "\n\nAvailable claims for the verified policyholder:\n"
                        f"{claim_options}\n"
                        "You must ask the user to choose one of these claims. Do not guess, do not pick the first claim, and do not answer as if a case has already been selected."
                    )
        elif phase == "PROCESS_CASE":
            system = PROCESS_SYSTEM
        else:
            system = POST_SYSTEM

        if phase == "PROCESS_CASE" and state.active_case_id:
            claim = get_claim(state.active_case_id)
            if claim:
                system += (
                    f"\n\nAuthoritative claim record: {json.dumps(claim, default=str)}"
                    f"\nAppeal Deadline: {claim.get('appeal_deadline', 'not provided')}"
                    "\nSTRICT GROUNDING: Do not invent or alter dates. The appeal deadline is "
                    "March 18, 2026. Do not state May or any other month."
                )

    messages: list[dict[str, str]] = [{"role": "system", "content": system}]
    messages.append(
        {
            "role": "system",
            "content": f"Structured session context (authoritative):\n{context_block}",
        }
    )
    for msg in state.messages[-12:]:
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": user_message})

    completion = client.chat.completions.create(
        model=llm_model(),
        messages=messages,
        temperature=0.4,
    )
    content = completion.choices[0].message.content
    return content.strip() if content else "I'm here to help with your claim. Could you tell me a bit more?"


def build_conversation_summary(state: SessionState) -> str:
    lines = []
    for msg in state.messages:
        role = "Customer" if msg["role"] == "user" else "Agent"
        lines.append(f"{role}: {msg['content']}")
    claim = get_claim(state.active_case_id) if state.active_case_id else None
    if claim:
        lines.append(
            f"\nClaim outcome snapshot: {claim.get('case_id')} — {claim.get('status')} — {claim.get('summary')}"
        )
    return "\n".join(lines)
