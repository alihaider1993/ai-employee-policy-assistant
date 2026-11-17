from types import SimpleNamespace

from app.rag import loader


def test_slugify_makes_search_safe_keys():
    assert loader.slugify("Print Holiday entitlement - GOV.UK") == "print-holiday-entitlement-gov-uk"
    assert loader.slugify("???") == "document"


def test_display_name_strips_print_prefix_and_falls_back_to_filename():
    assert loader.display_name("Print Redundancy: your rights - GOV.UK", "x.pdf") == "Redundancy: your rights - GOV.UK"
    assert loader.display_name("FCA Employee Handbook", "x.pdf") == "FCA Employee Handbook"
    assert loader.display_name(None, "data/policies/leave-policy.pdf") == "leave-policy"
    assert loader.display_name("", "data/policies/leave-policy.pdf") == "leave-policy"


def test_list_policy_files_returns_sorted_pdfs(tmp_path):
    for name in ("b.pdf", "a.pdf", "notes.txt"):
        (tmp_path / name).write_text("x")

    assert [p.name for p in loader.list_policy_files(tmp_path)] == ["a.pdf", "b.pdf"]


def test_chunk_ids_are_unique_across_documents(monkeypatch):
    def fake_load(file_path):
        return [
            SimpleNamespace(
                page_content=f"text {n} " * 200,
                metadata={"title": "Print Doc - GOV.UK", "page": n},
            )
            for n in range(3)
        ]

    monkeypatch.setattr(loader, "load_policy_document", fake_load)

    first = loader.build_chunk_records("data/policies/one.pdf")
    second = loader.build_chunk_records("data/policies/two.pdf")
    ids = [record["id"] for record in first + second]

    assert len(ids) == len(set(ids))
    assert ids[0] == "one-0"
    assert first[0]["source"] == "Doc - GOV.UK"
    assert first[0]["page"] == 0


def test_strip_link_paths_removes_relative_links_including_wrapped_ones():
    text = "classed as workers (/employment-status/worker) are entitled to SSP (/sick-leave-\npay-employees/eligibility) now (see page 3)."

    assert loader.strip_link_paths(text) == "classed as workers are entitled to SSP now (see page 3)."


def test_handbook_keeps_its_legacy_chunk_ids(monkeypatch):
    monkeypatch.setattr(
        loader,
        "load_policy_document",
        lambda file_path: [SimpleNamespace(page_content="text " * 300, metadata={"page": 0})],
    )

    records = loader.build_chunk_records("data/policies/fca_employee_handbook.pdf")

    assert records[0]["id"] == "chunk-0"
