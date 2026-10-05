"""Validate eval/golden_questions.json.

Run from the repo root: python eval/validate_golden.py
"""

import json
import sys
from collections import Counter
from pathlib import Path

GOLDEN_PATH = Path(__file__).parent / "golden_questions.json"

REQUIRED_FIELDS = (
    "id",
    "question",
    "type",
    "expected_label",
    "document",
    "expected_pages",
    "answer_key",
    "must_include",
    "expected_behaviour",
)
TYPES = ("policy", "general", "out_of_scope", "not_covered")
LABELS = ("policy_question", "general_question", "out_of_scope")
BEHAVIOURS = ("answer", "refuse")
FIRST_PAGE, LAST_PAGE = 1, 95  # printed page numbers of fca_employee_handbook.pdf


def validate(entries):
    if not isinstance(entries, list):
        return Counter(), ["top level must be a JSON list"]

    errors = []
    type_counts = Counter()
    seen_ids = set()

    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            errors.append(f"entry {index}: must be an object")
            continue

        name = f"entry {index} (id={entry.get('id')!r})"

        missing = [field for field in REQUIRED_FIELDS if field not in entry]
        if missing:
            errors.append(f"{name}: missing fields {', '.join(missing)}")

        entry_id = entry.get("id")
        if "id" in entry:
            if entry_id in seen_ids:
                errors.append(f"{name}: duplicate id")
            elif isinstance(entry_id, (str, int)):
                seen_ids.add(entry_id)
            else:
                errors.append(f"{name}: id must be a string or integer")

        entry_type = entry.get("type")
        if "type" in entry:
            type_counts[entry_type] += 1
            if entry_type not in TYPES:
                errors.append(f"{name}: type {entry_type!r} not one of {', '.join(TYPES)}")

        label = entry.get("expected_label")
        if "expected_label" in entry and label not in LABELS:
            errors.append(f"{name}: expected_label {label!r} not one of {', '.join(LABELS)}")

        behaviour = entry.get("expected_behaviour")
        if "expected_behaviour" in entry and behaviour not in BEHAVIOURS:
            errors.append(
                f"{name}: expected_behaviour {behaviour!r} not one of {', '.join(BEHAVIOURS)}"
            )

        if "expected_pages" in entry:
            pages = entry["expected_pages"]
            if not isinstance(pages, list):
                errors.append(f"{name}: expected_pages must be a list")
            else:
                bad = [
                    page
                    for page in pages
                    # bool is a subclass of int, so exclude it explicitly
                    if isinstance(page, bool)
                    or not isinstance(page, int)
                    or not FIRST_PAGE <= page <= LAST_PAGE
                ]
                if bad:
                    errors.append(
                        f"{name}: expected_pages must be integers {FIRST_PAGE}-{LAST_PAGE}, got {bad}"
                    )
                if not pages and entry_type == "policy":
                    errors.append(f"{name}: expected_pages is empty for a policy question")

    return type_counts, errors


def main():
    try:
        entries = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Could not load {GOLDEN_PATH}: {exc}")
        return 1

    type_counts, errors = validate(entries)

    print(f"{len(entries) if isinstance(entries, list) else 0} entries in {GOLDEN_PATH.name}")
    for entry_type in TYPES:
        print(f"  {entry_type}: {type_counts[entry_type]}")
    for entry_type, count in type_counts.items():
        if entry_type not in TYPES:
            print(f"  {entry_type!r} (invalid): {count}")

    if errors:
        print(f"\n{len(errors)} error(s):")
        for error in errors:
            print(f"  - {error}")
        return 1

    print("\nNo errors.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
