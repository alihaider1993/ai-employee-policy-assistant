from app.graph.nodes import route_question, route_review


def test_route_policy_question():
    state = {
        "question": "What is the annual leave policy?",
        "question_type": "policy_question",
        "answer": "",
        "review_status": "",
        "sources": [],
    }

    result = route_question(state)

    assert result == "policy_question"
    
    
def test_route_review():
    approved_state = {
        "question": "What is the annual leave policy?",
        "question_type": "policy_question",
        "answer": "Employees are entitled to annual leave.",
        "review_status": "approved",
        "sources": [],
    }

    rejected_state = {
        "question": "What is the annual leave policy?",
        "question_type": "policy_question",
        "answer": "",
        "review_status": "rejected",
        "sources": [],
    }

    assert route_review(approved_state) == "approved"
    assert route_review(rejected_state) == "rejected"

def test_review_prompt_includes_retrieved_context(monkeypatch):
    from types import SimpleNamespace

    from app.graph import nodes

    prompts = []

    class FakeLLM:
        def invoke(self, prompt):
            prompts.append(prompt)
            return SimpleNamespace(content="Approved\n")

    monkeypatch.setattr(nodes, "llm", FakeLLM())

    result = nodes.review_policy_answer(
        {
            "question": "What is the SSP rate?",
            "question_type": "policy_question",
            "answer": "It is 123.25 a week.",
            "review_status": "",
            "sources": [],
            "context": "Source: SSP guide\nPage: 1\nContent: weekly rate is 123.25",
        }
    )

    assert "weekly rate is 123.25" in prompts[0]
    assert result["review_status"] == "approved"
