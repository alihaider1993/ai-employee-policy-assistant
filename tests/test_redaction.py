import pytest

from app.core.redaction import redact_personal_data


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Email me at jo.smith@example.co.uk about leave", "Email me at [EMAIL] about leave"),
        ("Call 07700 900123 please", "Call [PHONE] please"),
        ("My number is +44 7700 900123.", "My number is [PHONE]."),
        ("Landline 020 7946 0958 works", "Landline [PHONE] works"),
        ("My NI number is AB 12 34 56 C", "My NI number is [NI NUMBER]"),
        ("Pay me to GB82 WEST 1234 5698 7654 32 thanks", "Pay me to [IBAN] thanks"),
        ("Card 4539 1488 0343 6467 was charged", "Card [CARD NUMBER] was charged"),
        ("The office is at SW1A 1AA", "The office is at [POSTCODE]"),
    ],
)
def test_identifiers_are_replaced(text, expected):
    redacted, counts = redact_personal_data(text)

    assert redacted == expected
    assert counts


@pytest.mark.parametrize(
    "text",
    [
        "How many days of annual leave do I get?",
        "SSP is 123.25 a week for up to 28 weeks",
        "Statutory redundancy pay is capped at 22530 after 6 April 2026",
        "A 5.6 week entitlement is 28 days for a 5 day week",
        "Section 199 of the Trade Union Act 1992 applies",
        "Is the number 1234 5678 9012 3456 valid?",
        "",
    ],
)
def test_ordinary_text_is_left_alone(text):
    redacted, counts = redact_personal_data(text)

    assert redacted == text
    assert counts == {}


def test_counts_report_each_kind_without_the_values():
    _, counts = redact_personal_data("a@b.com and c@d.com, call 07700 900123")

    assert counts == {"email": 2, "phone number": 1}
