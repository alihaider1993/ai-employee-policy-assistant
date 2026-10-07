from datetime import date

from sqlalchemy.dialects import postgresql

from app.database.daily_cap import reserve_daily_question


class FakeResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class FakeSession:
    """Records statements; the counter value it returns stands in for Postgres."""

    def __init__(self, returned_count):
        self.returned_count = returned_count
        self.statements = []
        self.commits = 0

    def execute(self, statement):
        self.statements.append(statement)
        return FakeResult(self.returned_count)

    def commit(self):
        self.commits += 1


def compiled_sql(statement):
    return str(statement.compile(dialect=postgresql.dialect()))


def test_counts_a_question_when_under_the_cap():
    db = FakeSession(returned_count=1)

    assert reserve_daily_question(db, cap=200, day=date(2026, 1, 1)) is True
    assert db.commits == 1


def test_refuses_when_postgres_returns_no_row():
    # ON CONFLICT ... WHERE questions < cap updates nothing at the cap, so no row comes back.
    db = FakeSession(returned_count=None)

    assert reserve_daily_question(db, cap=200, day=date(2026, 1, 1)) is False


def test_uses_one_atomic_upsert_guarded_by_the_cap():
    db = FakeSession(returned_count=1)

    reserve_daily_question(db, cap=200, day=date(2026, 1, 1))

    assert len(db.statements) == 1
    sql = compiled_sql(db.statements[0])
    assert "INSERT INTO daily_usage" in sql
    assert "ON CONFLICT (day) DO UPDATE SET questions = (daily_usage.questions +" in sql
    assert "WHERE daily_usage.questions <" in sql
    assert "RETURNING daily_usage.questions" in sql


def test_a_cap_below_one_refuses_without_querying():
    db = FakeSession(returned_count=1)

    assert reserve_daily_question(db, cap=0, day=date(2026, 1, 1)) is False
    assert db.statements == []
