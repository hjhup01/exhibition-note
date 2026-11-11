"""저장소 장애: DB를 열 수 없어도 목록·필터·상세는 쓰고, 기록 기능만 막힌다 (AppTest, 가짜 외부 호출)."""
from datetime import date
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from exhibition_app import config, culture_api, messages, repository
from exhibition_app.culture_api import Exhibition

TODAY = date(2026, 11, 11)
APP = Path(__file__).resolve().parent.parent / "app.py"
MSG = "기록 저장소를 열 수 없습니다. DB_PATH를 확인해 주세요."


def make(i, title, region="서울"):
    return Exhibition(i, title, "미술", region, "미술관", "2026-11-01", "2026-12-31")


@pytest.fixture(params=["directory", "parent_is_file"])
def broken_db(request, tmp_path, monkeypatch):
    if request.param == "directory":
        path = tmp_path / "adir"
        path.mkdir()
    else:
        blocker = tmp_path / "file"
        blocker.write_text("x")
        path = blocker / "sub" / "x.db"
    monkeypatch.setenv("DB_PATH", str(path))
    monkeypatch.setattr(config, "today_kst", lambda: TODAY)
    monkeypatch.setattr(culture_api, "fetch_exhibitions",
                        lambda *a, **k: [make("1", "빛의 전시"), make("2", "부산 전시", "부산")])
    return path


def run():
    at = AppTest.from_file(str(APP), default_timeout=30)
    at.run()
    assert not at.exception
    return at


def texts(at):
    return [m.value for m in at.markdown] + [m.value for m in at.caption]


def test_ac11_repository_reports_message(broken_db):
    assert repository.init_db(broken_db).message == MSG
    assert messages.STORE_UNAVAILABLE == MSG


def test_ac11_find_page_shows_message_and_disables_save(broken_db):
    at = run()
    assert MSG in texts(at)
    assert at.sidebar.radio[0].options == [messages.PAGE_FIND, messages.PAGE_MY]
    assert "내 전시" in [at.sidebar.radio[0].format_func(o) for o in at.sidebar.radio[0].options]
    at.button(key="pick-1").click().run()
    assert not at.exception
    assert at.button(key="save-1").disabled
    assert "빛의 전시" in [h.value for h in at.header]


def test_ac11_filters_still_work(broken_db):
    at = run()
    at.sidebar.selectbox[1].set_value("부산").run()
    assert not at.exception
    keys = [b.key for b in at.button]
    assert "pick-2" in keys and "pick-1" not in keys


def test_ac11_my_page_shows_only_message(broken_db):
    at = run()
    at.sidebar.radio[0].set_value(messages.PAGE_MY).run()
    assert not at.exception
    assert texts(at) == [MSG]
    assert not at.tabs
