from app.ai.client import llm
from app.rag.retriever import retrieve_policy_chunks

def generate_policy_answer(question: str):
    results = retrieve_policy_chunks(question)

    context_parts = []

    for result in results:
        context_part = (
            f"Source: {result['source']}\n"
            f"Page: {result['page']}\n"
            f"Content: {result['content']}"
        )

        context_parts.append(context_part)

    context = "\n\n---\n\n".join(context_parts)

    prompt = f"""
    You are an Employee Policy Assistant.

    Answer the user's question using only the policy context provided below.

    Rules:
    - Do not use outside knowledge.
    - Do not invent policy information.
    - If the context does not contain enough information to answer the question,
    say that the provided policy context does not contain enough information.
    - Give a clear and concise answer.
    - Mention the source and page when appropriate.

    Question:
    {question}

    Policy context:
    {context}
    """


    response = llm.invoke(prompt)

    sources = []

    for result in results:
        source = {
            "document": result["source"],
            "page": result["page"],
        }

        if source not in sources:
            sources.append(source)

    return {
        "answer": response.content,
        "sources": sources,
    }

