from types import SimpleNamespace

from app.core.rate_limit import DailyCapReached, RateLimiter
from app.schemas.ask import MAX_QUESTION_LENGTH, AskResponse, Source
from app.ui import format_answer, make_responder


def fake_request(ip="1.2.3.4"):
    return SimpleNamespace(headers={}, client=SimpleNamespace(host=ip))


def make_respond(answer_question, per_minute=5):
    return make_responder(answer_question, RateLimiter(per_minute), trusted_hops=1)


def test_format_answer_lists_sources():
    response = AskResponse(answer="Lock your screen.", sources=[Source(document="Handbook", page=23)])

    assert format_answer(response) == "Lock your screen.\n\n**Sources**\n- Handbook, page 23"


def test_format_answer_without_sources_is_just_the_answer():
    assert format_answer(AskResponse(answer="Out of scope.")) == "Out of scope."


def test_respond_passes_stripped_question_to_answer_function():
    asked = []

    def answer_question(question):
        asked.append(question)
        return AskResponse(answer="ok")

    assert make_respond(answer_question)("  What is the leave policy?  ", fake_request()) == "ok"
    assert asked == ["What is the leave policy?"]


def test_respond_rejects_empty_and_too_long_questions_without_calling_the_model():
    def answer_question(question):
        raise AssertionError("should not be called")

    respond = make_respond(answer_question)

    assert "Type a question" in respond("   ", fake_request())
    assert "under" in respond("x" * (MAX_QUESTION_LENGTH + 1), fake_request())


def test_respond_applies_rate_limit():
    respond = make_respond(lambda question: AskResponse(answer="ok"), per_minute=1)

    assert respond("first", fake_request()) == "ok"
    assert "too quickly" in respond("second", fake_request())


def test_respond_explains_the_daily_cap():
    def answer_question(question):
        raise DailyCapReached()

    assert make_respond(answer_question)("question", fake_request()) == DailyCapReached.message


def test_respond_hides_errors_from_the_user():
    def answer_question(question):
        raise KeyError("secret internal detail")

    message = make_respond(answer_question)("question", fake_request())

    assert "Something went wrong" in message
    assert "secret" not in message
