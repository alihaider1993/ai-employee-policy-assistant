import uuid

import gradio as gr
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.core.config import settings
from app.core.rate_limit import RateLimiter, client_ip
from app.database.connection import SessionLocal
from app.graph.workflow import policy_graph
from app.models.conversation import Conversation
from app.schemas.ask import AskRequest, AskResponse
from app.ui import build_ui

app = FastAPI(
    title=settings.app_name,
    description="Production-style AI employee policy assistant",
    version=settings.app_version,
)

# Shared by /ask and the UI so both count towards the same limits.
limiter = RateLimiter(settings.rate_limit_per_minute, settings.rate_limit_per_day)


def answer_question(question: str) -> AskResponse:
    db = SessionLocal()

    try:
        # Check whether this exact question was answered before
        cached_conversation = (
            db.query(Conversation)
            .filter(Conversation.question == question)
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
                "question": question,
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
            question=question,
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


@app.get("/", include_in_schema=False)
def home():
    return RedirectResponse(url="/ui")


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "environment": settings.environment,
    }


@app.post("/ask", response_model=AskResponse)
def ask_question(payload: AskRequest, request: Request):
    fallback = request.client.host if request.client else None
    refusal = limiter.check(client_ip(request.headers, fallback))
    if refusal:
        raise HTTPException(status_code=429, detail=refusal)

    return answer_question(payload.question)


app = gr.mount_gradio_app(app, build_ui(answer_question, limiter), path="/ui")
