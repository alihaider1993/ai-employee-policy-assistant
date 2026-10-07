from datetime import date

from sqlalchemy import Date, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.database.connection import Base


class DailyUsage(Base):
    """Questions sent to Azure OpenAI per UTC day, for the daily cap."""

    __tablename__ = "daily_usage"

    day: Mapped[date] = mapped_column(
        Date,
        primary_key=True,
    )

    questions: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
