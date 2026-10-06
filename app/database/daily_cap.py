from sqlalchemy.dialects.postgresql import insert

from app.models.daily_usage import DailyUsage


def reserve_daily_question(db, cap, day):
    """Count one question that will call Azure against day's cap.

    A single upsert increments the counter only while it is below cap, so
    concurrent requests and replicas can't overshoot. Returns False, without
    counting, once the cap is reached.
    """
    if cap < 1:
        return False

    statement = (
        insert(DailyUsage)
        .values(day=day, questions=1)
        .on_conflict_do_update(
            index_elements=[DailyUsage.day],
            set_={"questions": DailyUsage.questions + 1},
            where=DailyUsage.questions < cap,
        )
        .returning(DailyUsage.questions)
    )
    counted = db.execute(statement).scalar_one_or_none()
    db.commit()
    return counted is not None
