from review_app.job_store import JobStore


def test_job_store_preserves_request_and_marks_interrupted(tmp_path) -> None:
    store = JobStore(tmp_path / "jobs.db")
    store.save(
        "job-1",
        {
            "kind": "analysis",
            "status": "running",
            "message": "正在生成",
            "branches": {
                "excel": {"status": "succeeded", "message": "已完成"},
                "word": {"status": "running", "message": "正在分析"},
            },
        },
        {"filename": "复盘.txt", "text": "首板出身"},
    )

    store.mark_interrupted()

    restored = store.get("job-1")
    assert restored is not None
    assert restored["status"] == "failed"
    assert restored["branches"]["excel"]["status"] == "succeeded"
    assert restored["branches"]["word"]["status"] == "failed"
    assert store.get_request("job-1")["text"] == "首板出身"
