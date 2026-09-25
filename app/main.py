from fastapi import FastAPI


from app.core.config import settings
from app.graph.workflow import policy_graph
from app.schemas.ask import AskRequest, AskResponse

import uuid

from app.database.connection import SessionLocal
from app.models.conversation import Conversation

app = FastAPI(
    title=settings.app_name,
    description="Production-style AI employee policy assistant",
    version=settings.app_version,
)


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "environment": settings.environment,
    }

@app.post("/ask", response_model=AskResponse)
def ask_question(request: AskRequest):
    db = SessionLocal()

    try:
        # Check whether this exact question was answered before
        cached_conversation = (
            db.query(Conversation)
            .filter(Conversation.question == request.question)
            .order_by(Conversation.id.desc())
            .first()
        )

        # Return cached answer without calling LangGraph / Azure OpenAI
        if cached_conversation:
            return AskResponse(
                answer=cached_conversation.answer,
            )

        # No cached answer, so run the AI workflow
        result = policy_graph.invoke(
            {
                "question": request.question,
                "question_type": "",
                "answer": "",
                "review_status": "",
                "sources": [],
            }
        )

        # Create unique ID for this conversation
        session_id = str(uuid.uuid4())

        # Save the new question and answer
        conversation = Conversation(
            session_id=session_id,
            question=request.question,
            answer=result["answer"],
        )

        db.add(conversation)
        db.commit()

        return AskResponse(
            answer=result["answer"],
            sources=result["sources"],
        )

    finally:
        db.close()