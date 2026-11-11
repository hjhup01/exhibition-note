"""AC: 전시 목록 화면 - 공공 API 장애 (가짜 HTTP 계층, 고정 today)."""
import datetime
import json
import pathlib

import pytest
import requests
from streamlit.testing.v1 import AppTest

from exhibition_app import config, messages

APP = str(pathlib.Path(__file__).resolve().parent.parent / "app.py")
TODAY = datetime.date(2026, 11, 11)
FAILED = "전시 정보를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요."


class Resp:
    def __init__(self, text, status=200):
        self.text, self.status_code = text, status


def art(**kw):
    d = {"seq": "1", "title": "전시", "realmName": "전시", "area": "서울", "place": "관",
         "startDate": "20261001", "endDate": "20261231"}
    d.update(kw)
    return d


def jbody(item):
    return json.dumps({"response": {"body": {"items": {"item": item}}}})


def run_app(monkeypatch, resp=None, exc=None, calls=None):
    def fake_get(url, **kw):
        if calls is not None:
            calls.append(kw)
        if exc is not None:
            raise exc
        return resp

    monkeypatch.setattr(config, "today_kst", lambda: TODAY)
    monkeypatch.setattr(requests, "get", fake_get)
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    return at


def texts(at):
    return [m.value for m in at.markdown]


def test_ac3_messages_are_exact():
    assert messages.CULTURE_FAILED == FAILED and messages.NO_RESULT == "결과 없음"


@pytest.mark.parametrize("exc", [requests.Timeout("k"), requests.ConnectionError(), RuntimeError("x")])
def test_ac3_exception_shows_failure(monkeypatch, exc):
    at = run_app(monkeypatch, exc=exc)
    assert FAILED in texts(at) and not at.button


@pytest.mark.parametrize("status", [400, 500, 503])
def test_ac3_http_error_shows_failure(monkeypatch, status):
    assert FAILED in texts(run_app(monkeypatch, Resp("{}", status)))


@pytest.mark.parametrize("text", [
    "not json", "", "<html", "<a><b/></a>",
    "<response><body></body></response>",
    json.dumps({"x": 1}),
    json.dumps({"response": {}}),
    json.dumps({"response": {"body": {}}}),
    jbody({"a": 1}),
    jbody("str"),
])
def test_ac3_unparseable_or_bad_envelope_shows_failure(monkeypatch, text):
    at = run_app(monkeypatch, Resp(text))
    assert FAILED in texts(at) and messages.NO_RESULT not in texts(at)


@pytest.mark.parametrize("text", [
    json.dumps({"response": {"body": {"items": ""}}}),
    json.dumps({"response": {"body": {"items": {}}}}),
    jbody([]),
    "<response><body><items></items></body></response>",
])
def test_ac3_empty_items_shows_no_result(monkeypatch, text):
    at = run_app(monkeypatch, Resp(text))
    assert messages.NO_RESULT in texts(at) and FAILED not in texts(at) and not at.button


def test_ac3_xml_single_item_is_one_row(monkeypatch):
    xml = ("<response><body><items><item><seq>1</seq><title>하나</title>"
           "<realmName>전시</realmName><area>서울</area><place>관</place>"
           "<startDate>20261001</startDate><endDate>20261231</endDate></item></items></body></response>")
    at = run_app(monkeypatch, Resp(xml))
    assert [b.label for b in at.button] == ["하나"]


def test_ac3_filter_matching_nothing_shows_no_result(monkeypatch):
    at = run_app(monkeypatch, Resp(jbody([art()])))
    at.sidebar.text_input[0].set_value("없는제목").run()
    assert not at.exception and messages.NO_RESULT in texts(at) and not at.button


def test_ac3_only_non_art_items_shows_no_result(monkeypatch):
    at = run_app(monkeypatch, Resp(jbody([art(realmName="공연")])))
    assert messages.NO_RESULT in texts(at)


def test_ac3_single_call_with_timeout_10(monkeypatch):
    calls = []
    run_app(monkeypatch, Resp(jbody([art()])), calls=calls)
    assert len(calls) == 1 and calls[0]["timeout"] == 10
    calls.clear()
    run_app(monkeypatch, exc=requests.Timeout(), calls=calls)
    assert len(calls) == 1 and calls[0]["timeout"] == 10


def test_ac3_secret_not_on_screen(monkeypatch):
    monkeypatch.setenv("CULTURE_API_KEY", "SENTINEL-KEY")
    at = run_app(monkeypatch, exc=RuntimeError("SENTINEL-KEY"))
    assert "SENTINEL-KEY" not in " ".join(texts(at))
