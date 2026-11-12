"""실제 관람일, 칸별 스크롤 컨테이너, 관심 저장 버튼 강조."""
import sqlite3
from datetime import date
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from exhibition_app import config, culture_api, messages, repository, search_api, summarizer
from exhibition_app.culture_api import Exhibition

TODAY = date(2026, 11, 11)
APP = str(Path(__file__).resolve().parent.parent / "src" / "app.py")
APP_SRC = Path(APP).read_text(encoding="utf-8")
EX = Exhibition("1", "빛의 층위", "전시", "서울", "한강아트센터", "2026-10-02", "2027-01-18")


# ---------- 저장 규칙 ----------

@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "x.db")
    assert repository.init_db(path).ok
    assert repository.save(path, EX).ok
    assert repository.plan(path, "1", "2026-11-10").ok
    return path


def row(path):
    with sqlite3.connect(path) as c:
        c.row_factory = sqlite3.Row
        return dict(c.execute("SELECT * FROM saved_exhibition").fetchone())


def test_complete_stores_actual_date_and_keeps_planned(db):
    assert repository.complete(db, "1", "2026-11-09", today=TODAY).ok
    r = row(db)
    assert (r["status"], r["planned_visit_date"], r["actual_visit_date"]) == ("관람완료", "2026-11-10", "2026-11-09")


@pytest.mark.parametrize("bad,msg", [
    ("2026-02-30", messages.INVALID_ACTUAL_DATE), ("20261109", messages.INVALID_ACTUAL_DATE),
    ("", messages.INVALID_ACTUAL_DATE), ("2026-11-12", messages.FUTURE_ACTUAL_DATE)])
def test_complete_rejects_bad_or_future_actual_date_and_row_unchanged(db, bad, msg):
    before = row(db)
    res = repository.complete(db, "1", bad, today=TODAY)
    assert not res.ok and res.message == msg
    assert row(db) == before


def test_today_is_allowed_as_actual_date(db):
    assert repository.complete(db, "1", TODAY.isoformat(), today=TODAY).ok


def test_change_actual_date_only_when_done(db):
    res = repository.change_actual_date(db, "1", "2026-11-09", today=TODAY)
    assert not res.ok and res.message == messages.ACTUAL_DATE_STATE
    assert repository.complete(db, "1", "2026-11-09", today=TODAY).ok
    assert repository.change_actual_date(db, "1", "2026-11-08", today=TODAY).ok
    assert row(db)["actual_visit_date"] == "2026-11-08"
    before = row(db)
    assert not repository.change_actual_date(db, "1", "2026-11-30", today=TODAY).ok
    assert row(db) == before


def test_old_db_without_column_is_migrated(tmp_path):
    path = str(tmp_path / "old.db")
    old_schema = repository.SCHEMA.replace("    actual_visit_date TEXT,\n", "")
    with sqlite3.connect(path) as c:
        c.execute(old_schema)
        c.execute("INSERT INTO saved_exhibition (exhibition_id,title,category,region,place,start_date,end_date,"
                  "status,planned_visit_date,created_at,updated_at) VALUES ('1','A','전시','서울','P',"
                  "'2026-11-01','2026-12-31','관람예정','2026-11-10','t','t')")
    assert repository.init_db(path).ok
    assert repository.init_db(path).ok  # 두 번 실행해도 안전
    assert repository.complete(path, "1", "2026-11-10", today=TODAY).ok
    assert row(path)["actual_visit_date"] == "2026-11-10"


# ---------- 화면 ----------

@pytest.fixture
def app_env(tmp_path, monkeypatch):
    path = str(tmp_path / "x.db")
    monkeypatch.setenv("DB_PATH", path)
    monkeypatch.setattr(config, "today_kst", lambda: TODAY)
    monkeypatch.setattr(culture_api, "fetch_exhibitions", lambda *a, **k: [EX])
    empty = {"items": [], "message": messages.NO_RESULT, "failed": False}
    monkeypatch.setattr(search_api, "load_related", lambda *a, **k: {"web": dict(empty), "blogs": dict(empty)})
    monkeypatch.setattr(summarizer, "summarize", lambda *a, **k: "")
    return path


def test_complete_from_screen_with_actual_date_then_change(app_env):
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.button(key="pick-1").click().run()
    at.button(key="save-1").click().run()
    at.radio(key="page").set_value(messages.PAGE_MY).run()
    at.date_input(key="plan-date-1").set_value(date(2026, 11, 20)).run()
    at.button(key="plan-1").click().run()
    # 예정일이 미래면 실제 관람일 기본값은 오늘
    assert at.date_input(key="actual-date-1").value == TODAY
    at.date_input(key="actual-date-1").set_value(date(2026, 11, 8)).run()
    at.button(key="done-1").click().run()
    assert not at.exception
    r = row(app_env)
    assert (r["status"], r["planned_visit_date"], r["actual_visit_date"]) == ("관람완료", "2026-11-20", "2026-11-08")
    captions = [c.value for c in at.caption]
    assert any("관람예정일 2026-11-20" in c and "실제 관람일 2026-11-08" in c for c in captions)
    # 관람완료 탭에서 실제 관람일 변경
    at.date_input(key="actual-change-date-1").set_value(date(2026, 11, 7)).run()
    at.button(key="actual-change-1").click().run()
    assert row(app_env)["actual_visit_date"] == "2026-11-07"
    assert messages.ACTUAL_DATE_CHANGED_DONE in [m.value for m in at.markdown]


def test_find_page_panes_scroll_independently_and_save_button_is_primary(app_env):
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.button(key="pick-1").click().run()
    left, right = at.columns[0], at.columns[1]
    for col in (left, right):
        kinds = [type(c).__name__ for c in col.children.values()]
        assert kinds == ["Html", "Block"]  # 칸 제목(스크롤 밖) + 스크롤 컨테이너 하나
    assert 'container(height=PANE_HEIGHT, key="list-pane")' in APP_SRC
    assert 'container(height=PANE_HEIGHT, key="detail-pane")' in APP_SRC
    save = at.button(key="save-1")
    assert save.proto.type == "primary"
    assert "st-key-save-" in APP_SRC and "SAVE_BUTTON_COLOR" in APP_SRC
    assert ".st-key-detail-pane h2" in APP_SRC


def test_pane_titles_follow_filters(app_env):
    at = AppTest.from_file(APP, default_timeout=30).run()
    titles = lambda: [h.proto.body for h in at.columns[0].get("html")] + [h.proto.body for h in at.columns[1].get("html")]
    assert any("서울 - 전시중인 목록" in t for t in titles())
    assert any("전시 상세" in t for t in titles())
    at.sidebar.selectbox(key="period").set_value("전시예정").run()
    at.sidebar.multiselect(key="regions").set_value([]).run()
    assert any("전체 - 전시예정인 목록" in t for t in titles())
    at.sidebar.selectbox(key="period").set_value("전체").run()
    assert any("전체 - 전체 기간 목록" in t for t in titles())
