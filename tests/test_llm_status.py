"""AWS 키 만료(인증 오류) 때: 요약은 잠시 건너뛰고, AI 도우미·API는 알맞은 안내를 한다."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import agent
from exhibition_app import llm_status, messages, summarizer

APP = str(Path(__file__).resolve().parent.parent / "src" / "app.py")
WEB = [{"title": "글", "description": "내용"}]


class FakeClientError(Exception):
    """botocore.exceptions.ClientError 흉내(이름·문구만)."""


def auth_error():
    return FakeClientError("An error occurred (UnrecognizedClientException) when calling the InvokeModel "
                           "operation: The security token included in the request is invalid.")


@pytest.mark.parametrize("exc", [
    auth_error(),
    RuntimeError("Error raised by bedrock service: ExpiredTokenException: token expired"),
    type("NoCredentialsError", (Exception,), {})("Unable to locate credentials"),
])
def test_auth_errors_are_recognized(exc):
    assert llm_status.is_auth_error(exc)


def test_wrapped_auth_error_is_recognized():
    try:
        try:
            raise auth_error()
        except FakeClientError as inner:
            raise ValueError("bedrock call failed") from inner
    except ValueError as outer:
        assert llm_status.is_auth_error(outer)


@pytest.mark.parametrize("exc", [TimeoutError("read timed out"), RuntimeError("ThrottlingException"),
                                 ValueError("bad json")])
def test_other_errors_are_not_auth_errors(exc):
    assert not llm_status.is_auth_error(exc)


def test_summary_skips_llm_after_auth_error():
    calls = []

    def failing(system, user):
        calls.append(1)
        raise auth_error()

    assert summarizer.summarize(WEB, [], invoke=failing) == ""
    assert summarizer.summarize(WEB, [], invoke=failing) == ""  # 두 번째는 부르지 않는다
    assert len(calls) == 1
    assert not llm_status.available()


def test_summary_keeps_trying_after_non_auth_error():
    calls = []

    def flaky(system, user):
        calls.append(1)
        raise TimeoutError("timeout")

    summarizer.summarize(WEB, [], invoke=flaky)
    summarizer.summarize(WEB, [], invoke=flaky)
    assert len(calls) == 2 and llm_status.available()


def test_cooldown_expires():
    llm_status.mark_failed(now=1000.0)
    assert not llm_status.available(now=1000.0 + llm_status.COOLDOWN_SECONDS - 1)
    assert llm_status.available(now=1000.0 + llm_status.COOLDOWN_SECONDS)


def test_agent_run_says_ai_unavailable_without_calling_graph():
    llm_status.mark_failed()

    class Boom:
        def invoke(self, *a, **k):
            raise AssertionError("그래프를 부르면 안 된다")

    r = agent.run("서울 전시 추천", graph=Boom())
    assert r["answer"] == messages.AI_UNAVAILABLE
    assert r["contexts"] == [] and r["trace"][0]["step"] == "llm_check"


def test_agent_run_switches_fallback_to_ai_unavailable_on_auth_error():
    class AuthFailGraph:
        def invoke(self, *a, **k):
            llm_status.note(auth_error())  # 그래프 안의 모델 호출이 인증 오류로 실패한 상황
            return {"answer": agent.FALLBACK_ANSWER, "contexts": [], "trace": []}

    assert agent.run("서울 전시 추천", graph=AuthFailGraph())["answer"] == messages.AI_UNAVAILABLE


def test_agent_run_keeps_retry_message_for_other_failures():
    class TimeoutGraph:
        def invoke(self, *a, **k):
            return {"answer": agent.FALLBACK_ANSWER, "contexts": [], "trace": []}

    assert agent.run("서울 전시 추천", graph=TimeoutGraph())["answer"] == agent.FALLBACK_ANSWER


def test_assistant_page_shows_notice_when_ai_unavailable(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "x.db"))
    llm_status.mark_failed()
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.sidebar.radio[0].set_value(messages.PAGE_ASSISTANT).run()
    assert not at.exception
    assert messages.AI_UNAVAILABLE in [i.value for i in at.info]
