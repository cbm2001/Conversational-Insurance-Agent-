from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

Phase = Literal["VERIFY_ID", "RESOLVE_INTENT", "PROCESS_CASE", "POST_PROCESS"]


class SessionState(BaseModel):
    session_id: str
    phase: Phase = "VERIFY_ID"
    collected_pii: dict = Field(default_factory=dict)
    verified_party_id: Optional[str] = None
    is_representative: bool = False
    pending_hints: dict = Field(default_factory=dict)
    active_case_id: Optional[str] = None
    out_of_scope_strikes: int = 0
    email_summary_offered: bool = False
    email_summary_decision: Optional[str] = None
    messages: list[dict] = Field(default_factory=list)
