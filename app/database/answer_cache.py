import uuid

from sqlalchemy import select

from app.models.conversation import Conversation


def normalize_question(question):
    """The cache key for a question: whitespace trimmed and collapsed, case kept."""
    return " ".join(question.split())


def find_cached_answer(db, question, cache_version):
    statement = (
        select(Conversation)
        .where(
            Conversation.cache_version == cache_version,
            Conversation.question == question,
        )
        .order_by(Conversation.id.desc())
        .limit(1)
    )
    return db.scalars(statement).first()


def save_answer(db, question, answer, sources, cache_version):
    db.add(
        Conversation(
            # Not a real session: every saved answer gets a new id.
            session_id=str(uuid.uuid4()),
            question=question,
            answer=answer,
            sources=sources,
            cache_version=cache_version,
        )
    )
    db.commit()
