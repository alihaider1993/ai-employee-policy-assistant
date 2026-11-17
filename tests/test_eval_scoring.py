from eval.run_eval import score_retrieval


def test_hit_requires_matching_document_and_page():
    result = score_retrieval(
        pages=[5, 5, 2],
        sources=["FCA Employee Handbook", "Holiday entitlement - GOV.UK", "Holiday entitlement - GOV.UK"],
        expected_pages=[5],
        expected_source="Holiday entitlement - GOV.UK",
    )

    assert result["hit"] is True
    assert result["first_hit_rank"] == 2


def test_same_page_in_the_wrong_document_is_a_miss():
    result = score_retrieval(
        pages=[5],
        sources=["FCA Employee Handbook"],
        expected_pages=[5],
        expected_source="Holiday entitlement - GOV.UK",
    )

    assert result["hit"] is False
    assert result["first_hit_rank"] is None


def test_distinct_pages_count_each_document_separately():
    result = score_retrieval(
        pages=[1, 1],
        sources=["FCA Employee Handbook", "Holiday entitlement - GOV.UK"],
        expected_pages=[1],
        expected_source="FCA Employee Handbook",
    )

    assert result["distinct_pages"] == 2
