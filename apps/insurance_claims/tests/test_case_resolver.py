from harness.case_resolver import resolve_case


def test_generic_healthcare_claim_is_unresolved_when_multiple_claims_exist():
    assert resolve_case("P9", {"case_type": "healthcare"}) is None


def test_broad_healthcare_january_is_ambiguous_and_not_auto_selected():
    assert resolve_case("P9", {"case_type": "healthcare", "month": "january"}) is None


def test_denied_healthcare_january_still_resolves_to_specific_claim():
    assert resolve_case("P9", {"case_type": "healthcare", "month": "january", "status": "denied"}) == "CL-2048"
