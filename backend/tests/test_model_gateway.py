from app.core.config import settings
from app.services.model_gateway import generate_embedding, summarize_story


def test_embedding_fallback_without_openai_key(monkeypatch) -> None:
    monkeypatch.setattr(settings, "openai_api_key", None)
    emb = generate_embedding("OpenAI launches an agent SDK", dimensions=8)
    assert len(emb) == 8
    assert all(isinstance(v, float) for v in emb)


def test_summary_fallback_outputs_up_to_max_bullets(monkeypatch) -> None:
    monkeypatch.setattr(settings, "openai_api_key", None)
    headline, bullets = summarize_story(
        "OpenAI launches new agent tools",
        ["OpenAI released tools for developers to build autonomous workflows."],
    )
    assert headline
    assert 1 <= len(bullets) <= 3
    assert all(isinstance(bullet, str) and bullet for bullet in bullets)


def test_summary_respects_requested_bullet_cap(monkeypatch) -> None:
    monkeypatch.setattr(settings, "openai_api_key", None)
    _, bullets = summarize_story(
        "OpenAI launches new agent tools",
        [
            "First detail line.",
            "Second detail line.",
            "Third detail line.",
        ],
        max_bullets=2,
    )
    assert len(bullets) == 2


def test_summary_injects_relevance_bullet_when_missing(monkeypatch) -> None:
    monkeypatch.setattr(settings, "openai_api_key", None)
    _, bullets = summarize_story(
        "Apple iOS 17 update ships now",
        [
            "The update improves settings pages and lock screen widgets.",
            "Rollout begins this week.",
        ],
        max_bullets=2,
    )
    assert len(bullets) == 2
    assert any("tech relevance:" in bullet.lower() for bullet in bullets)


def test_summary_keeps_existing_relevance_bullet(monkeypatch) -> None:
    monkeypatch.setattr(settings, "openai_api_key", None)
    _, bullets = summarize_story(
        "Apple Intelligence update expands AI tools",
        [
            "Apple announced AI features for developers with new APIs.",
            "Rollout includes model tooling on device.",
        ],
        max_bullets=2,
    )
    assert len(bullets) == 2
    assert any(any(term in bullet.lower() for term in ("ai", "api", "model")) for bullet in bullets)
