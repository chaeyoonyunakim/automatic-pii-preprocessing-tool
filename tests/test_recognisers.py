"""Rule-layer recognisers: the folded-in NHS staff / org / UK identifiers.

NHS-number checksum + surface forms are covered separately in test_nhs_number.py.
"""
from src.recognisers import GMC, NHS_ODS, NMC, RECORD_ID, find_rule_spans


def _types(text: str) -> set[str]:
    return {s.entity_type for s in find_rule_spans(text)}


def test_clinician_and_org_ids():
    text = "Seen by Dr Lee GMC 1234567, nurse NMC 12A3456B, practice code P81026."
    t = _types(text)
    assert GMC in t and NMC in t and NHS_ODS in t


def test_postcode_date_email_phone():
    text = "Lives SW1A 1AA, dob 12/03/1981, email a@b.com, tel 07700 900123."
    assert {"UK_POSTCODE", "DATE_TIME", "EMAIL_ADDRESS", "PHONE_NUMBER"} <= _types(text)


def test_record_uuid():
    assert RECORD_ID in _types("note 550e8400-e29b-41d4-a716-446655440000 created")


def test_uk_nino():
    from src.recognisers import UK_NINO
    assert UK_NINO in _types("NI: AB 12 34 56 C")


def test_uk_vehicle_registration():
    from src.recognisers import UK_VEHICLE_REGISTRATION
    assert UK_VEHICLE_REGISTRATION in _types("vehicle AB12 CDE")
