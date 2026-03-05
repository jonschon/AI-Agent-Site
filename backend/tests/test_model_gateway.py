from app.core.config import settings
from app.services.model_gateway import generate_embedding, summarize_story


def test_embedding_fallback_without_openai_key(monkeypatch) -> None:
    monkeypatch.setattr(settings, "openai_api_key", None)
    emb = generate_embedding("OpenAI launches an agent SDK", dimensions=8)
    assert len(emb) == 8
    assert all(isinstance(v, float) for v in emb)


def test_summary_fallback_outputs_three_bullets(monkeypatch) -> None:
    monkeypatch.setattr(settings, "openai_api_key", None)
    headline, bullets = summarize_story(
        "OpenAI launches new agent tools",
        ["OpenAI released tools for developers to build autonomous workflows."],
    )
    assert headline
    assert len(bullets) == 3
    assert all(isinstance(bullet, str) and bullet for bullet in bullets)
