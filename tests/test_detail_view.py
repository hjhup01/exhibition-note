"""AC: 전시 상세 화면 - 선택 전·선택 후 (오른쪽 단 구성과 순서)."""
import datetime
import json
import pathlib

from streamlit.testing.v1 import AppTest

from exhibition_app import config, culture_api, messages, search_api, summarizer

APP = str(pathlib.Path(__file__).resolve().parent.parent / "app.py")
TODAY = datetime.date(2026, 11, 11)
ITEM = {"seq": "1", "title": "빛의 전시", "realmName": "전시", "area": "서울", "place": "시립미술관",
        "startDate": "20261001", "endDate": "20261231"}


def run_app(monkeypatch, tmp_path):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(config, "today_kst", lambda: TODAY)
    body = json.dumps({"response": {"body": {"items": {"item": [ITEM]}}}})
    monkeypatch.setattr(culture_api, "fetch_exhibitions",
                        lambda *a, **k: culture_api.parse_response(body))
    calls = []
    monkeypatch.setattr(search_api, "load_related", lambda t, **k: calls.append(t) or {
        "web": {"items": [], "message": messages.NO_RESULT, "failed": False},
        "blogs": {"items": [], "message": messages.NO_RESULT, "failed": False}})
    monkeypatch.setattr(summarizer, "summarize", lambda *a, **k: "")
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    at.calls = calls
    return at


def right_texts(at):
    return [str(el.value) for el in at.columns[1].children.values()
            if hasattr(el, "value") and isinstance(el.value, str)]


def test_ac12_nothing_selected_shows_only_prompt(monkeypatch, tmp_path):
    at = run_app(monkeypatch, tmp_path)
    right = at.columns[1]
    assert [m.value for m in right.markdown] == [messages.SELECT_EXHIBITION]
    assert len(right.button) == 0 and len(right.header) == 0
    assert at.calls == []


def test_ac12_selected_shows_detail_in_order(monkeypatch, tmp_path):
    at = run_app(monkeypatch, tmp_path)
    at.button[0].click().run()
    assert not at.exception
    right = at.columns[1]
    assert messages.SELECT_EXHIBITION not in [m.value for m in right.markdown]
    assert right.header[0].value == "빛의 전시"
    assert right.button[0].label == messages.SAVE_INTEREST_BUTTON
    values = [m.value for m in right.markdown]
    assert values[:2] == ["시립미술관", "2026-10-01 ~ 2026-12-31"]
    assert [s.value for s in right.subheader] == [messages.WEB_HEADING, messages.BLOG_HEADING]
    # 상세 칸 내용은 따로 스크롤되는 고정 높이 컨테이너 하나 안에 들어 있다
    panes = [c for c in right.children.values() if type(c).__name__ != "Html"]
    assert len(panes) == 1
    kinds = [type(c).__name__ for c in panes[0].children.values()]
    assert kinds.index("Button") < kinds.index("Subheader")
    assert at.calls == ["빛의 전시"]
