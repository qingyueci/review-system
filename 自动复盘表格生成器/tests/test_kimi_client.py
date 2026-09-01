from types import SimpleNamespace

import review_app.analysis as analysis_module


def test_kimi_client_uses_long_timeout_without_automatic_retry(monkeypatch) -> None:
    captured: dict = {}

    class FakeOpenAI:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)
            message = SimpleNamespace(content="# 今日核心判断\n测试完成")
            completion = SimpleNamespace(
                choices=[SimpleNamespace(message=message)],
                model="kimi-test",
                usage=SimpleNamespace(
                    prompt_tokens=120,
                    completion_tokens=30,
                    total_tokens=150,
                ),
            )
            def create(**kwargs):
                captured["requested_model"] = kwargs["model"]
                captured["thinking"] = kwargs["extra_body"]["thinking"]["type"]
                captured["reasoning_effort"] = kwargs.get("reasoning_effort")
                return completion

            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=create)
            )

    monkeypatch.setattr(analysis_module, "OpenAI", FakeOpenAI)
    sources = [
        {
            "title": "测试资料",
            "published_at": "2026-07-18",
            "source_type": "manual",
            "source_url": "https://example.com",
            "content": "首板出身决定原始任务",
        }
    ]

    metrics = {}
    result = analysis_module.analyze_with_rag(
        "test-key",
        "测试复盘",
        sources,
        model="deepseek-v4-pro",
        thinking_enabled=True,
        metrics=metrics,
    )

    assert result.startswith("# 今日核心判断")
    assert captured["timeout"] == 300
    assert captured["max_retries"] == 0
    assert captured["requested_model"] == "deepseek-v4-pro"
    assert captured["thinking"] == "enabled"
    assert captured["reasoning_effort"] == "high"
    assert metrics["model"] == "kimi-test"
    assert metrics["usage"]["total_tokens"] == 150
