from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"


def _load_json(name: str) -> Any:
    path = FIXTURES_DIR / name
    with path.open(encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def _policyholders() -> list[dict[str, Any]]:
    return _load_json("policyholders.json")


@lru_cache(maxsize=1)
def _claims() -> list[dict[str, Any]]:
    return _load_json("claims.json")


@lru_cache(maxsize=1)
def _representatives() -> list[dict[str, Any]]:
    return _load_json("representatives.json")


@lru_cache(maxsize=1)
def document_guidelines() -> dict[str, Any]:
    return _load_json("required_document_guideline.json")


def get_policyholder(party_id: str) -> dict[str, Any] | None:
    for row in _policyholders():
        if row.get("party_id") == party_id:
            return row
    return None


def get_claims(party_id: str) -> list[dict[str, Any]]:
    return [c for c in _claims() if c.get("party_id") == party_id]


def get_claim(case_id: str) -> dict[str, Any] | None:
    for row in _claims():
        if row.get("case_id") == case_id:
            return row
    return None


def get_representative(name: str) -> dict[str, Any] | None:
    normalized = _normalize_name(name)
    for rep in _representatives():
        if _normalize_name(rep.get("rep_name", "")) == normalized:
            return rep
    return None


def all_policyholders() -> list[dict[str, Any]]:
    return list(_policyholders())


def all_representatives() -> list[dict[str, Any]]:
    return list(_representatives())


def _normalize_name(value: str) -> str:
    return " ".join(value.lower().split())
