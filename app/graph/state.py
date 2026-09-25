from typing import TypedDict


class PolicyAssistantState(TypedDict):
    question: str
    question_type: str
    answer: str
    review_status: str
    sources: list[dict]