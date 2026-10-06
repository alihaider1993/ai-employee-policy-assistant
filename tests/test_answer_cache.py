from types import SimpleNamespace

import pytest

from app import main
from app.core.rate_limit import DailyCapReached
from app.database.answer_cache import normalize_question
from app.models.conversation import Conversation

SOURCES = [{"document": "Handbook", "page": 24}]


class FakeSession:
    """Stands in for a SQLAlchemy session, answering cache lookups from rows."""

    def __init__(self, rows=()):
        self.rows = list(rows)
        self.commits = 0
        self.closed = False

    def scalars(self, statement):
        params = statement.compile().params
        version = next(value for key, value in params.items() if key.startswith("cache_version"))
        question = next(value for key, value in params.items() if key.startswith("question"))
        matches = sorted(
            (row for row in self.rows if row.cache_version == version and row.question == question),
            key=lambda row: row.id,
            reverse=True,
        )
        return SimpleNamespace(first=lambda: matches[0] if matches else None)

    def add(self, row):
        row.id = len(self.rows) + 1
        self.rows.append(row)

    def commit(self):
        self.commits += 1

    def close(self):
        self.closed = True


class FakeGraph:
    def __init__(self):
        self.questions = []

    def invoke(self, state):
        self.questions.append(state["question"])
        return {**state, "answer": "Fresh answer.", "sources": SOURCES}


def cached_row(question, cache_version, answer="Cached answer.", sources=SOURCES, row_id=1):
    return Conversation(
        id=row_id,
        session_id="s",
        question=question,
        answer=answer,
        sources=sources,
        cache_version=cache_version,
    )


@pytest.fixture
def app_with(monkeypatch):
    """Point answer_question at a fake session, graph and daily cap."""

    def configure(rows=(), cap_allows=True):
        db = FakeSession(rows)
        graph = FakeGraph()
        reserved = []

        def reserve(session, cap, day):
            reserved.append(day)
            return cap_allows

        monkeypatch.setattr(main, "SessionLocal", lambda: db)
        monkeypatch.setattr(main, "policy_graph", graph)
        monkeypatch.setattr(main, "reserve_daily_question", reserve)
        monkeypatch.setattr(main.settings, "cache_version", "1")
        return db, graph, reserved

    return configure


def test_normalize_question_trims_and_collapses_whitespace_but_keeps_case():
    assert normalize_question("  What is\tthe  Leave policy?\n") == "What is the Leave policy?"


def test_cache_hit_returns_cached_answer_and_sources_without_calling_azure(app_with):
    db, graph, reserved = app_with(rows=[cached_row("What is X?", "1")])

    response = main.answer_question("What is X?")

    assert response.answer == "Cached answer."
    assert [source.model_dump() for source in response.sources] == SOURCES
    assert graph.questions == []
    assert reserved == []
    assert db.closed


def test_cache_hit_ignores_whitespace_differences(app_with):
    _, graph, _ = app_with(rows=[cached_row("What is X?", "1")])

    assert main.answer_question("  What   is X? ").answer == "Cached answer."
    assert graph.questions == []


def test_cache_is_case_sensitive(app_with):
    _, graph, _ = app_with(rows=[cached_row("What is X?", "1")])

    assert main.answer_question("what is x?").answer == "Fresh answer."
    assert graph.questions == ["what is x?"]


def test_answers_cached_under_another_version_are_ignored(app_with):
    db, graph, reserved = app_with(rows=[cached_row("What is X?", "0")])

    response = main.answer_question("What is X?")

    assert response.answer == "Fresh answer."
    assert graph.questions == ["What is X?"]
    assert len(reserved) == 1
    saved = db.rows[-1]
    assert (saved.question, saved.cache_version, saved.sources) == ("What is X?", "1", SOURCES)


def test_cache_miss_saves_normalized_question_with_sources_then_hits(app_with):
    db, graph, reserved = app_with()

    first = main.answer_question(" What is X? ")
    second = main.answer_question("What is X?")

    assert first == second
    assert graph.questions == ["What is X?"]
    assert len(reserved) == 1
    assert len(db.rows) == 1


def test_daily_cap_stops_azure_calls_but_not_cached_answers(app_with):
    db, graph, _ = app_with(rows=[cached_row("What is X?", "1")], cap_allows=False)

    assert main.answer_question("What is X?").answer == "Cached answer."
    with pytest.raises(DailyCapReached):
        main.answer_question("What is Y?")
    assert graph.questions == []
    assert len(db.rows) == 1
