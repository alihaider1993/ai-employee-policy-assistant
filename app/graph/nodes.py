from app.ai.client import llm
from app.graph.state import PolicyAssistantState
from app.rag.generator import generate_policy_answer


def classify_question(state: PolicyAssistantState) -> PolicyAssistantState:
    prompt = f"""
    You are classifying questions for an Employee Policy Assistant.

    Classify the question into exactly one category:

    - policy_question: A question about workplace policies, employee rights,
    leave, sickness, absence, working hours, holidays, maternity/paternity,
    benefits, conduct, bullying, harassment, whistleblowing, or other
    employment-related rules or procedures.

    - general_question: A normal general-knowledge question that is not about
    employee policies or workplace rules.

    - out_of_scope: A request unrelated to both employee policies and normal
    general questions, such as coding, creative writing, or unrelated tasks.

    Question:
    {state["question"]}

    Return only one of:
    policy_question
    general_question
    out_of_scope
    """

    response = llm.invoke(prompt)

    return {
        **state,
        "question_type": response.content.strip(),
    }

def route_question(state: PolicyAssistantState) -> str:
    return state["question_type"]


def generate_answer(state: PolicyAssistantState) -> PolicyAssistantState:
    response = llm.invoke(state["question"])

    return {
        **state,
        "answer": response.content,
    }
    
def generate_policy_rag_answer(
    state: PolicyAssistantState,
) -> PolicyAssistantState:
    rag_result = generate_policy_answer(
        state["question"]
    )

    return {
        **state,
        "answer": rag_result["answer"],
        "sources": rag_result["sources"],
    }

def handle_out_of_scope(
    state: PolicyAssistantState,
) -> PolicyAssistantState:

    return {
        **state,
        "answer": (
            "I can help with employee policy and workplace-related questions. "
            "This request is outside the scope of the Employee Policy Assistant."
        ),
    }
    
    
def review_policy_answer(
    state: PolicyAssistantState,
) -> PolicyAssistantState:

    prompt = f"""
    You are reviewing an answer produced by an Employee Policy Assistant.

    Question:
    {state["question"]}

    Answer:
    {state["answer"]}

    Check whether the answer:
    - addresses the user's question
    - is clear and professional
    - avoids unsupported or overly confident claims
    - clearly states when there is not enough information

    Return only one word:

    approved
    rejected
    """

    response = llm.invoke(prompt)

    return {
        **state,
        "review_status": response.content.strip().lower(),
    }
    
def route_review(state: PolicyAssistantState) -> str:
    return state["review_status"]


def handle_rejected_answer(
    state: PolicyAssistantState,
) -> PolicyAssistantState:
    return {
        **state,
        "answer": (
            "I could not produce a sufficiently reliable answer "
            "from the available policy information."
        ),
    }