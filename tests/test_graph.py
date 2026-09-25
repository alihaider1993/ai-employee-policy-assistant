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