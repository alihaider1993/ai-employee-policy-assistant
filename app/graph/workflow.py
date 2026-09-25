from langgraph.graph import END, START, StateGraph

from app.graph.nodes import (
    classify_question,
    generate_answer,
    generate_policy_rag_answer,
    handle_out_of_scope,
    handle_rejected_answer,
    review_policy_answer,
    route_question,
    route_review,
)
from app.graph.state import PolicyAssistantState


def build_graph():
    graph = StateGraph(PolicyAssistantState)
    graph.add_node("classify_question", classify_question)

    graph.add_node("generate_answer", generate_answer)
    
    graph.add_node(
        "generate_policy_rag_answer",
        generate_policy_rag_answer,
    )
    
    graph.add_node(
        "handle_out_of_scope",
        handle_out_of_scope,
    )
    graph.add_node(
        "review_policy_answer",
        review_policy_answer,
    )
    graph.add_node(
        "handle_rejected_answer",
        handle_rejected_answer,
    )

   
    graph.add_edge(START, "classify_question")
    graph.add_conditional_edges(
    "classify_question",
    route_question,
        {
            "policy_question": "generate_policy_rag_answer",
            "general_question": "generate_answer",
            "out_of_scope": "handle_out_of_scope",
        },
    )
    graph.add_edge("generate_answer", END)
    graph.add_edge(
        "generate_policy_rag_answer",
        "review_policy_answer",
    )

    graph.add_conditional_edges(
        "review_policy_answer",
        route_review,
        {
            "approved": END,
            "rejected": "handle_rejected_answer",
        },
    )

    graph.add_edge(
        "handle_rejected_answer",
        END,
    )
    graph.add_edge("handle_out_of_scope", END)

    return graph.compile()


policy_graph = build_graph()