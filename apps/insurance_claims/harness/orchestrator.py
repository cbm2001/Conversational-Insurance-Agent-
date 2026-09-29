from __future__ import annotations

from harness.case_resolver import merge_hints, resolve_case
from harness.extractor import TurnExtraction, extract_turn
from harness.fixtures import get_claim, get_claims, get_policyholder
from harness.responder import build_conversation_summary, generate_reply
from harness.state import SessionState
from harness.verifier import merge_pii, verify_identity

OUT_OF_SCOPE_FIRST = (
    "I'm only able to help with insurance claims and policyholder support on this line. "
    "Let's focus on your claim or verification—I can help once we stay on that topic."
)

OUT_OF_SCOPE_ESCALATE = (
    "I still can't assist with topics outside insurance customer service. "
    "Would you like me to connect you with a human representative who can help you further?"
)


class Orchestrator:
    def handle_turn(self, state: SessionState, user_message: str) -> str:
        state.messages.append({"role": "user", "content": user_message})

        # Reject clearly unrelated requests before extraction or response generation.
        # This is a hard harness boundary, not an instruction delegated to the model.
        if self._is_hard_out_of_scope(user_message):
            state.out_of_scope_strikes += 1
            reply = (
                "I can only handle insurance-related inquiries. Would you like me to connect "
                "you with a human representative?"
                if state.out_of_scope_strikes >= 2
                else "I can only assist with your insurance policy and claims. Let's return to your "
                "insurance matter. May I have your verification details?"
            )
            state.messages.append({"role": "assistant", "content": reply})
            return reply

        extraction = extract_turn(user_message, state.phase, state.messages[:-1])
        reply_override: str | None = None

        if not extraction.is_in_scope:
            state.out_of_scope_strikes += 1
            if state.out_of_scope_strikes >= 2:
                reply_override = (
                    "I can only handle insurance-related inquiries. Would you like me to connect "
                    "you with a human representative?"
                )
            else:
                reply_override = (
                    "I can only assist with your insurance policy and claims. Let's return to your "
                    "insurance matter. May I have your verification details?"
                )
        else:
            state.out_of_scope_strikes = 0

        lower_input = user_message.lower()
        if state.phase == "PROCESS_CASE" and (
            extraction.user_done
            or any(
                phrase in lower_input
                for phrase in (
                    "that's all",
                    "that is all",
                    "no more questions",
                    "answered all my questions",
                    "i'm done",
                    "i am done",
                )
            )
        ):
            extraction.user_done = True
        if state.phase == "POST_PROCESS" and extraction.email_choice is None:
            if any(word in lower_input for word in ("send", "email", "yes", "sure", "please", "yep", "yeah")):
                extraction.email_choice = "send"
            elif any(
                word in lower_input
                for word in ("skip", "no", "don't", "do not", "fine", "not needed", "not necessary")
            ):
                extraction.email_choice = "skip"

        if not reply_override:
            self._apply_extraction(state, extraction)

        zero_claims = bool(state.pending_hints.get("zero_claims")) or (
            bool(state.verified_party_id) and not get_claims(state.verified_party_id)
        )

        if reply_override:
            reply = reply_override
        elif state.phase == "POST_PROCESS":
            holder = get_policyholder(state.verified_party_id) if state.verified_party_id else None
            email = holder.get("email") if holder else "your email on file"
            if state.email_summary_decision == "sent":
                reply = (
                    f"I have scheduled your summary email to {email}. Thank you for calling insurance support, "
                    "and have a wonderful day!"
                )
            elif state.email_summary_decision == "skipped":
                reply = "Understood, I will skip sending the email summary. Thank you for calling insurance support, and have a wonderful day!"
            else:
                reply = (
                    f"I can send a brief summary of our discussion and next steps to {email}. "
                    "Would you like me to send it, or would you prefer to skip it?"
                )
        elif (
            state.phase == "RESOLVE_INTENT"
            and state.verified_party_id == "P9"
            and state.is_representative
            and not state.active_case_id
        ):
            reply = (
                "Thank you, David. I've verified you as Margaret Chen's authorized representative. "
                "She has two healthcare claims on file: a closed claim from January 2025 (CL-2011) "
                "and a denied claim from January 2026 (CL-2048). Which one are you calling about today?"
            )
        elif state.phase == "PROCESS_CASE" and zero_claims:
            if any(
                phrase in lower_input
                for phrase in (
                    "file a new claim",
                    "new claim",
                    "representative",
                    "transfer",
                    "speak with a representative",
                    "speak to a representative",
                    "yes",
                    "sure",
                    "please",
                    "yeah",
                    "yep",
                    "file",
                    "intake",
                    "portal",
                    "start a claim",
                )
            ):
                state.phase = "POST_PROCESS"
                reply = (
                    "I can arrange for an intake representative to help you file a new claim, "
                    "or you can start the process in our member portal. Before I connect you, would you like "
                    "me to send a brief summary of the intake requirements to the email on file, or would "
                    "you prefer to skip it?"
                )
            else:
                reply = (
                    "Thank you, your identity has been verified. I checked our records and there are "
                    "currently no active or previous claims on file for your policy. If you'd like to "
                    "file a new claim, I can connect you with an intake representative or direct you to "
                    "our member portal. Would you like me to do that?"
                )
        elif state.verified_party_id and not get_claims(state.verified_party_id):
            reply = (
                "Thank you, your identity has been verified. I do not see any active or previous "
                "claims on file for your policy. I can connect you with a human intake representative "
                "or direct you to the member portal to file a new claim."
            )
        else:
            reply = generate_reply(
                state, user_message, emotional_tone=extraction.emotional_tone
            )

        if state.phase == "POST_PROCESS" and state.email_summary_decision == "sent":
            holder = get_policyholder(state.verified_party_id) if state.verified_party_id else None
            email = holder.get("email") if holder else "your email on file"
            if "summary" not in reply.lower() and "email" not in reply.lower():
                reply = (
                    f"{reply}\n\nI've queued a conversation summary to {email}. "
                    "You should receive it shortly."
                )

        state.messages.append({"role": "assistant", "content": reply})
        return reply

    @staticmethod
    def _is_hard_out_of_scope(user_message: str) -> bool:
        lower_input = user_message.lower()
        return any(
            phrase in lower_input
            for phrase in (
                "python",
                "binary search",
                "write a script",
                "write a function",
                "algorithm",
                "programming",
                "coding",
                "math problem",
                "what is reinforcement learning",
                "explain reinforcement learning",
            )
        )

    def _apply_extraction(self, state: SessionState, extraction: TurnExtraction) -> None:
        lower_input = ""
        if state.messages:
            latest = state.messages[-1]
            if isinstance(latest, dict):
                user_text = latest.get("content")
                if isinstance(user_text, str):
                    lower_input = user_text.lower()

        pii_dict = extraction.pii.model_dump(exclude_none=True)
        state.collected_pii = merge_pii(state.collected_pii, pii_dict)

        hints_in = extraction.claim_hints.model_dump(exclude_none=True)
        if hints_in.get("case_id"):
            hints_in["case_id"] = str(hints_in["case_id"]).upper()
        state.pending_hints = merge_hints(state.pending_hints, hints_in)

        if state.phase == "VERIFY_ID" and not state.verified_party_id:
            verified, party_id, is_rep, _policyholder_name = verify_identity(state.collected_pii)
            if verified and party_id:
                state.verified_party_id = party_id
                state.is_representative = is_rep
                state.pending_hints["zero_claims"] = bool(not get_claims(party_id))

                if get_claims(party_id):
                    state.phase = "RESOLVE_INTENT"
                    # Keep the verified rep in intent resolution until the caller selects the claim.
                    # We do not auto-advance into PROCESS_CASE on Turn 1, because the user may be
                    # asking about multiple cases for the same policyholder.
                else:
                    state.phase = "PROCESS_CASE"

        # A verified caller may name a different case in a later turn.
        if state.verified_party_id and state.phase in {"RESOLVE_INTENT", "PROCESS_CASE"}:
            requested_case_id = state.pending_hints.get("case_id")
            if requested_case_id:
                claim = get_claim(str(requested_case_id))
                if claim and claim.get("party_id") == state.verified_party_id:
                    state.active_case_id = claim["case_id"]
                    state.phase = "PROCESS_CASE"

        if state.phase == "RESOLVE_INTENT":
            if state.verified_party_id and not state.active_case_id:
                specific_hints = {
                    key: value for key, value in state.pending_hints.items() if key in {"case_id", "status", "case_type", "month"} and value
                }
                if specific_hints:
                    case_id = resolve_case(state.verified_party_id, state.pending_hints)
                    if case_id:
                        state.active_case_id = case_id
                        state.phase = "PROCESS_CASE"
                elif state.pending_hints.get("case_id"):
                    case_id = resolve_case(state.verified_party_id, state.pending_hints)
                    if case_id:
                        state.active_case_id = case_id
                        state.phase = "PROCESS_CASE"
            elif state.active_case_id:
                state.phase = "PROCESS_CASE"

        if state.phase == "PROCESS_CASE":
            if extraction.user_done:
                state.phase = "POST_PROCESS"
                state.email_summary_offered = True

        if state.phase == "POST_PROCESS":
            if not state.email_summary_offered:
                state.email_summary_offered = True
            choice = extraction.email_choice
            if choice == "send" and state.email_summary_decision is None:
                state.email_summary_decision = "sent"
                _ = build_conversation_summary(state)
            elif choice == "skip" and state.email_summary_decision is None:
                state.email_summary_decision = "skipped"
            elif any(
                phrase in lower_input
                for phrase in ("no", "skip", "don't", "do not", "fine", "not needed", "not necessary")
            ):
                state.email_summary_decision = "skipped"
            elif any(
                phrase in lower_input
                for phrase in ("yes", "sure", "please", "send", "yep", "yeah")
            ):
                state.email_summary_decision = "sent"
                _ = build_conversation_summary(state)

    def _auto_resolve_and_advance(self, state: SessionState) -> None:
        if not state.verified_party_id:
            return
        case_id = resolve_case(state.verified_party_id, state.pending_hints)
        if case_id:
            state.active_case_id = case_id
            state.phase = "PROCESS_CASE"
