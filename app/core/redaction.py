"""Remove common personal identifiers from a question before it is stored or sent to a model.

Pattern-based, so it catches structured identifiers only: email addresses, phone
numbers, UK National Insurance numbers, IBANs, payment card numbers (Luhn
checked) and UK postcodes. It cannot find names or free-text details such as
"my manager Jo Smith at the Leeds office". Keep this module free of app.core.config
imports so it stays testable without a .env.
"""

import re

EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){2,7}(?:\s?[A-Z0-9]{1,4})?\b")
NATIONAL_INSURANCE = re.compile(
    r"\b[A-CEGHJ-PR-TW-Z][A-CEGHJ-NPR-TW-Z]\s?\d{2}\s?\d{2}\s?\d{2}\s?[A-D]\b", re.IGNORECASE
)
CARD = re.compile(r"(?<![\d-])(?:\d[ -]?){12,18}\d(?![\d-])")
PHONE = re.compile(r"(?<![\w.])(?:\+\d{1,3}[\s-]?|0)\d(?:[\s-]?\d){8,10}(?![\w])")
POSTCODE = re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2}\b", re.IGNORECASE)


def _luhn_valid(digits: str) -> bool:
    total = 0
    for index, char in enumerate(reversed(digits)):
        number = int(char)
        if index % 2 == 1:
            number *= 2
            if number > 9:
                number -= 9
        total += number
    return total % 10 == 0


def _redact_cards(text: str, counts: dict) -> str:
    def replace(match):
        digits = re.sub(r"\D", "", match.group(0))
        if 13 <= len(digits) <= 19 and _luhn_valid(digits):
            counts["card number"] = counts.get("card number", 0) + 1
            return "[CARD NUMBER]"
        return match.group(0)

    return CARD.sub(replace, text)


def redact_personal_data(text: str) -> tuple[str, dict]:
    """Return the text with identifiers replaced by placeholders, and how many of each kind."""
    counts: dict = {}

    def sub(pattern, placeholder, kind, value):
        redacted, number = pattern.subn(placeholder, value)
        if number:
            counts[kind] = counts.get(kind, 0) + number
        return redacted

    text = sub(EMAIL, "[EMAIL]", "email", text)
    text = sub(IBAN, "[IBAN]", "iban", text)
    text = sub(NATIONAL_INSURANCE, "[NI NUMBER]", "national insurance number", text)
    text = _redact_cards(text, counts)
    text = sub(PHONE, "[PHONE]", "phone number", text)
    text = sub(POSTCODE, "[POSTCODE]", "postcode", text)
    return text, counts
