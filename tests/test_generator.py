from types import SimpleNamespace

from app.rag import generator


def test_generator_uses_printed_page_numbers(monkeypatch):
    chunks = [
        {"source": "Handbook", "page": 23, "content": "Lock your screen."},
        {"source": "Handbook", "page": 23, "content": "Never share passwords."},
        {"source": "Handbook", "page": 24, "content": "Report theft."},
    ]
    prompts = []

    class FakeLLM:
        def invoke(self, prompt):
            prompts.append(prompt)
            return SimpleNamespace(content="answer")

    monkeypatch.setattr(generator, "retrieve_policy_chunks", lambda question: chunks)
    monkeypatch.setattr(generator, "llm", FakeLLM())

    result = generator.generate_policy_answer("How do I secure my laptop?")

    assert result["sources"] == [
        {"document": "Handbook", "page": 24},
        {"document": "Handbook", "page": 25},
    ]
    assert "Page: 24" in prompts[0]
    assert "Page: 25" in prompts[0]
    assert "Page: 23" not in prompts[0]
