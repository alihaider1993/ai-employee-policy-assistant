from datetime import datetime

from sqlalchemy import JSON, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.connection import Base


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        # Cache lookups match on both columns.
        Index("ix_conversations_cache_version_question", "cache_version", "question"),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    session_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
    )

    question: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    answer: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    # Rows from before cache versioning are '0'; see CACHE_VERSION in settings.
    cache_version: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default="0",
    )

    # The answer's {document, page} sources, returned with cached answers.
    sources: Mapped[list | None] = mapped_column(
        JSON,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )