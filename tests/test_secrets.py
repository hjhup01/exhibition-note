"""AC: 비밀 보호 - 센티넬 키 값이 화면·로그(DEBUG)·stdout/stderr 어디에도 나타나지 않는다."""
import datetime
import json
import logging
import pathlib
import sys
import types

import pytest
import requests
from streamlit.testing.v1 import AppTest

from exhibition_app import config, messages

APP = str(pathlib.Path(__file__).resolve().parent.parent / "src" / "app.py")
TODAY = datetime.date(2026, 11, 11)
SECRETS = {
    "CULTURE_API_KEY": "SENTINEL-CULTURE-9f3a1",
    "KAKAO_REST_API_KEY": "SENTINEL-KAKAO-7b2c4",
    "AWS_ACCESS_KEY_ID": "SENTINEL-AWSID-1a2b3",
    "AWS_SECRET_ACCESS_KEY": "SENTINEL-AWSSEC-4c5d6",
    "AWS_SESSION_TOKEN": "SENTINEL-AWSTOKEN-2e3f4",
    "LANGSMITH_API_KEY": "SENTINEL-LANGSMITH-8e9f0",
}
LEAK = " ".join(SECRETS.values())
CULTURE_LIST = {"response": {"body": {"items": {"item": [
    {"seq": "1", "title": "빛의 전시", "realmName": "전시", "area": "서울", "place": "미술관",
     "startDate": "20261001", "endDate": "20261231"}]}}}}
SEARCH_OK = {"documents": [{"title": "<b>글</b>", "url": "http://x/1", "contents": "설명",
                             "datetime": "2026-11-09T10:00:00.000+09:00"}]}


class Resp:
    def __init__(self, payload=None, status=200):
        self.payload, self.status_code = payload, status
        self.text = json.dumps(payload) if payload is not None else "not json " + LEAK

    def json(self):
        if self.payload is None:
            raise ValueError(LEAK)
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} for url: {CULTURE_URL}?serviceKey={LEAK}")


CULTURE_URL = "https://apis.data.go.kr/x"


def leaky(url):
    return requests.HTTPError(f"500 Server Error for url: {url}?serviceKey={LEAK}&id={LEAK}")


def make_get(culture, search):
    """culture/search(카카오): 'ok' | 'raise' | 'http500' | 'garbage'."""
    def get(url, *a, **k):
        mode = search if "kakao" in url else culture
        payload = SEARCH_OK if "kakao" in url else CULTURE_LIST
        if mode == "raise":
            raise leaky(url)
        if mode == "http500":
            return Resp(payload, 500)
        if mode == "garbage":
            return Resp(None)
        return Resp(payload)
    return get


class FakeChat:
    fail = False

    def __init__(self, *a, **k):
        pass

    def invoke(self, *a, **k):
        if FakeChat.fail:
            raise RuntimeError(f"Bedrock failed {LEAK}")
        return types.SimpleNamespace(content="한 줄\n두 줄", text=lambda: "한 줄\n두 줄")

    def __or__(self, other):
        return self


def walk(block):
    for child in block.children.values():
        if hasattr(child, "children") and child.children:
            yield from walk(child)
        proto = getattr(child, "proto", None)
        if proto is not None:
            yield str(proto)


def screen(at):
    parts = list(walk(at.main)) + list(walk(at.sidebar)) + [str(e.value) for e in at.exception]
    return "\n".join(parts)


@pytest.fixture
def env(monkeypatch, tmp_path):
    for k, v in SECRETS.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setattr(config, "today_kst", lambda: TODAY)
    import langchain_aws
    monkeypatch.setattr(langchain_aws, "ChatBedrock", FakeChat)
    try:
        import exhibition_app.summarizer as s
        if hasattr(s, "ChatBedrock"):
            monkeypatch.setattr(s, "ChatBedrock", FakeChat)
    except ImportError:
        pass
    FakeChat.fail = False
    sys.modules.pop("app", None)
    return monkeypatch


def go_pages(at):
    """목록 → 상세 선택 → 내 전시 페이지를 거친다. 각 단계의 화면 문자열을 돌려준다."""
    seen = [screen(at)]
    picks = [b for b in at.button if str(getattr(b, "key", "")).startswith("pick-")] or list(at.button)
    if picks:
        picks[0].click().run()
        seen.append(screen(at))
    radios = at.sidebar.radio
    if radios:
        mine = [o for o in radios[0].options if o.startswith(messages.PAGE_MY)]
        if mine:
            radios[0].set_value(mine[0]).run()
            seen.append(screen(at))
    return seen


SCENARIOS = [
    ("all_ok", "ok", "ok", False),
    ("culture_exception", "raise", "ok", False),
    ("culture_http500", "http500", "ok", False),
    ("culture_garbage", "garbage", "ok", False),
    ("search_exception", "ok", "raise", False),
    ("search_http500", "ok", "http500", False),
    ("search_garbage", "ok", "garbage", False),
    ("llm_fail", "ok", "ok", True),
    ("all_fail", "raise", "raise", True),
]


@pytest.mark.parametrize("name,culture,search,llm_fail", SCENARIOS, ids=[s[0] for s in SCENARIOS])
def test_ac7_no_secret_on_screen_logs_or_streams(env, capsys, caplog, name, culture, search, llm_fail):
    caplog.set_level(logging.DEBUG)
    logging.getLogger().setLevel(logging.DEBUG)
    env.setattr(requests, "get", make_get(culture, search))
    FakeChat.fail = llm_fail
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    seen = go_pages(at)
    cap = capsys.readouterr()
    blob = "\n".join(seen + [cap.out, cap.err, caplog.text])
    for key, value in SECRETS.items():
        assert value not in blob, f"{key} leaked in {name}"


def test_ac7_db_failure_screen_does_not_leak(env, tmp_path, capsys, caplog):
    caplog.set_level(logging.DEBUG)
    logging.getLogger().setLevel(logging.DEBUG)
    env.setenv("DB_PATH", str(tmp_path))  # 디렉터리 자체라 열 수 없다
    env.setattr(requests, "get", make_get("ok", "ok"))
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    seen = go_pages(at)
    cap = capsys.readouterr()
    blob = "\n".join(seen + [cap.out, cap.err, caplog.text])
    for key, value in SECRETS.items():
        assert value not in blob, f"{key} leaked on DB failure"


LIB_LOGGERS = ["requests", "urllib3", "botocore", "langchain", "langsmith"]


def test_ac7_library_loggers_redact_direct_debug_records(env, capsys, caplog):
    import io
    at = AppTest.from_file(APP, default_timeout=30)
    env.setattr(requests, "get", make_get("ok", "ok"))
    at.run()
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    config.install_secret_redaction()
    root.addHandler(handler)
    root.handlers[-1].addFilter(config.SecretRedactionFilter(config.secret_values()))
    caplog.set_level(logging.DEBUG)
    try:
        for name in LIB_LOGGERS:
            lg = logging.getLogger(name)
            lg.setLevel(logging.DEBUG)
            lg.debug("GET https://x/?serviceKey=%s&k=%s", LEAK, SECRETS["LANGSMITH_API_KEY"])
    finally:
        root.removeHandler(handler)
    cap = capsys.readouterr()
    blob = "\n".join([stream.getvalue(), cap.out, cap.err, caplog.text])
    for value in SECRETS.values():
        assert value not in blob
    assert config.REDACTED in blob
