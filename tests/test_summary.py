import re

import pytest

from exhibition_app import config, summarizer
from exhibition_app.summarizer import summarize


def items(n):
    return [{"title": f"t{i}", "description": f"d{i}"} for i in range(n)]


def test_ac5_seven_lines_trimmed_to_five():
    out = summarize(items(2), [], invoke=lambda s, u: "\n".join(f"줄{i}" for i in range(1, 8)))
    assert out.splitlines() == [f"줄{i}" for i in range(1, 6)]


def test_ac5_blank_lines_skipped_before_limit():
    raw = "\n\n".join(f"줄{i}" for i in range(1, 8))
    assert summarize(items(1), items(1), invoke=lambda s, u: raw).splitlines() == \
        [f"줄{i}" for i in range(1, 6)]


def test_ac5_single_call_per_summarize():
    calls = []
    summarize(items(1), items(1), invoke=lambda s, u: calls.append(1) or "ok")
    assert len(calls) == 1


def test_ac5_works_without_langsmith_key(monkeypatch):
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    assert summarize(items(1), [], invoke=lambda s, u: "ok") == "ok"


def test_ac5_langsmith_send_failure_does_not_hide_summary(monkeypatch):
    # 트레이서 전송 예외는 라이브러리 안에서 삼켜지므로 invoke 결과가 그대로 보인다
    monkeypatch.setenv("LANGSMITH_API_KEY", "bad")
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    assert summarize(items(1), [], invoke=lambda s, u: "ok2") == "ok2"


@pytest.mark.parametrize("exc", [RuntimeError("x"), TimeoutError("read timeout"), OSError("net")])
def test_ac5_llm_failure_gives_no_summary(exc):
    def boom(s, u):
        raise exc
    assert summarize(items(1), items(1), invoke=boom) == ""


@pytest.mark.parametrize("resp", ["", "  \n \n", None])
def test_ac5_empty_response_gives_no_summary(resp):
    assert summarize(items(1), [], invoke=lambda s, u: resp) == ""


def test_ac5_no_related_means_no_llm_call():
    calls = []
    assert summarize([], [], invoke=lambda s, u: calls.append(1) or "x") == ""
    assert calls == []


def test_ac5_one_side_empty_still_summarizes():
    calls = []
    out = summarize([], items(1), invoke=lambda s, u: calls.append(u) or "ok")
    assert out == "ok" and len(calls) == 1


def test_ac5_default_invoke_failure_swallowed(monkeypatch):
    def fake(system, user, env=None):
        raise TimeoutError("read timeout")
    monkeypatch.setattr(summarizer, "_default_invoke", fake)
    assert summarize(items(1), []) == ""


def test_ac5_model_id_selection():
    assert config.bedrock_client_config({"BEDROCK_MODEL_ID": " my.model "})["model_id"] == "my.model"
    assert config.bedrock_client_config({})["model_id"] == config.DEFAULT_BEDROCK_MODEL_ID
    assert config.bedrock_client_config({"BEDROCK_MODEL_ID": "  "})["model_id"] == \
        config.DEFAULT_BEDROCK_MODEL_ID
    assert re.match(r"^((global|us|eu|apac)\.)?anthropic\.claude-", config.DEFAULT_BEDROCK_MODEL_ID)


def test_ac5_bedrock_client_config_timeouts():
    cfg = config.bedrock_client_config({})["config"]
    assert cfg.connect_timeout == 10 and cfg.read_timeout == 10
    assert cfg.retries["total_max_attempts"] == 1


def test_ac5_default_invoke_passes_config_to_chatbedrock(monkeypatch):
    import langchain_aws
    seen = {}

    class FakeChat:
        def __init__(self, **kw):
            seen.update(kw)

        def invoke(self, msgs):
            class M:
                content = "요약"
            return M()

    monkeypatch.setattr(langchain_aws, "ChatBedrock", FakeChat)
    assert summarize(items(1), [], env={"BEDROCK_MODEL_ID": "us.anthropic.claude-x"}) == "요약"
    assert seen["model_id"] == "us.anthropic.claude-x"
    assert seen["config"].read_timeout == 10
