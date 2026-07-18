from types import SimpleNamespace

import review_app.analysis as analysis_module


def test_kimi_client_uses_long_timeout_without_automatic_retry(monkeypatch) -> None:
    captured: dict = {}

    class FakeOpenAI:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)
            message = SimpleNamespace(content="# 今日核心判断\n测试完成")
            completion = SimpleNamespace(choices=[SimpleNamespace(message=message)])
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=lambda **_kwargs: completion)
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

    result = analysis_module.analyze_with_rag("test-key", "测试复盘", sources)

    assert result.startswith("# 今日核心判断")
    assert captured["timeout"] == 300
    assert captured["max_retries"] == 0
