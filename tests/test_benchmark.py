import json
from types import SimpleNamespace

import pytest
from skitz_music import benchmark


def test_extract_preserves_single_source():
    assert benchmark.extract_lilypond('```lilypond\n\\version "2.24.3"\n```').startswith(
        "\\version"
    )
    with pytest.raises(ValueError):
        benchmark.extract_lilypond("No notation was produced")
    with pytest.raises(ValueError):
        benchmark.extract_lilypond("```ly\none\n```\n```ly\ntwo\n```")


def test_one_shot_never_receives_repair_feedback(tmp_path, monkeypatch):
    calls = []
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("compose test")

    def response(*args, **kwargs):
        calls.append(json.loads(kwargs["input"]))
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {"text": "bad notation", "usage": {}, "elapsedMs": 1, "stopReason": "stop"}
            ),
        )

    monkeypatch.setattr(benchmark.subprocess, "run", response)
    result = benchmark.run_benchmark(
        str(prompt), str(tmp_path / "run"), "single-response", "gpt-5.5", 8
    )
    assert len(calls) == 1
    assert calls[0]["prompt"] == "compose test"
    assert result["first_attempt_passed"] is False
    assert (tmp_path / "run/attempt-01/response.txt").read_text() == "bad notation"
