"""내 전시 화면: 저장 상태 반영 (AppTest, 가짜 문화포털, 임시 DB_PATH)."""
import sqlite3
from pathlib import Path
from datetime import date

import pytest
from streamlit.testing.v1 import AppTest

from exhibition_app import config, culture_api, messages, repository
from exhibition_app.culture_api import Exhibition

TODAY = date(2026, 11, 11)
APP = str(Path(__file__).resolve().parent.parent / "src" / "app.py")


def make(i, title, place="미술관"):
    return Exhibition(i, title, "미술", "서울", place, "2026-11-01", "2026-12-31")


@pytest.fixture
def env(tmp_path, monkeypatch):
    db = str(tmp_path / "sub" / "x.db")
    monkeypatch.setenv("DB_PATH", db)
    monkeypatch.setattr(config, "today_kst", lambda: TODAY)
    state = {"items": [make("1", "A전"), make("2", "B전")]}
    monkeypatch.setattr(culture_api, "fetch_exhibitions", lambda *a, **k: list(state["items"]))
    return db, state


def run():
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    assert not at.exception
    return at


def texts(at):
    return [m.value for m in at.markdown] + [m.value for m in at.caption]


def pick_and_save(at, key):
    at.button(key=f"pick-{key}").click().run()
    at.button(key=f"save-{key}").click().run()
    assert not at.exception
    return at


def go_my(at):
    at.radio(key="page").set_value(messages.PAGE_MY).run()
    assert not at.exception
    return at


def tab_texts(at, idx):
    # idx: 0=관심, 1=관람예정, 2=관람완료 (맨 앞 '전체' 탭 다음부터)
    t = at.tabs[idx + 1]
    # 상태 탭은 한 줄 목록(펼침 상자): 상자 제목의 첫 부분이 전시 제목이다
    return [m.value for m in t.markdown] + [e.label.split(" · ")[0] for e in t.expander]


def rows(db):
    with sqlite3.connect(db) as c:
        return c.execute("SELECT COUNT(*) FROM saved_exhibition").fetchone()[0]


def test_ac8_save_snapshot_count_duplicate_delete_restart(env):
    db, state = env
    at = run()
    assert "내 전시(0)" in at.radio(key="page").options
    pick_and_save(at, "1")
    assert rows(db) == 1
    with sqlite3.connect(db) as c:
        r = c.execute("SELECT title,place,region,category,start_date,end_date,status FROM"
                      " saved_exhibition").fetchone()
    assert r == ("A전", "미술관", "서울", "미술", "2026-11-01", "2026-12-31", "관심")

    at = go_my(at)
    assert tab_texts(at, 0).count("A전") == 1
    assert "A전" not in tab_texts(at, 1) and "A전" not in tab_texts(at, 2)
    assert any("내 전시(1)" in str(o) for o in at.radio(key="page").options) or \
        "내 전시(1)" in at.radio(key="page").options

    # 재저장
    at.radio(key="page").set_value(messages.PAGE_FIND).run()
    at.button(key="pick-1").click().run()
    at.button(key="save-1").click().run()
    assert messages.ALREADY_SAVED in texts(at)
    assert rows(db) == 1

    # API 값이 바뀌어도 스냅샷 유지, 재시작 후에도 유지
    state["items"] = [make("1", "바뀐 제목", "다른 장소")]
    at2 = go_my(run())
    assert "A전" in tab_texts(at2, 0)
    assert "바뀐 제목" not in tab_texts(at2, 0)
    assert "내 전시(1)" in at2.radio(key="page").options

    # 삭제
    at2.button(key="del-1").click().run()
    at2.button(key="del-1-yes").click().run()  # 삭제는 한 번 더 확인한다
    assert rows(db) == 0
    for i in range(3):
        assert "A전" not in tab_texts(at2, i)
    assert "내 전시(0)" in at2.radio(key="page").options


def test_ac8_tab_order_updated_at_desc_then_id(env):
    db, _ = env
    repository.init_db(db)
    for i, t in (("1", "A전"), ("2", "B전"), ("3", "C전")):
        repository.save(db, make(i, t))
    with sqlite3.connect(db) as c:
        c.execute("UPDATE saved_exhibition SET updated_at='2026-01-01T00:00:00' WHERE exhibition_id='1'")
        c.execute("UPDATE saved_exhibition SET updated_at='2026-02-01T00:00:00' WHERE exhibition_id IN ('2','3')")
        c.execute("UPDATE saved_exhibition SET status='관람예정', planned_visit_date='2026-11-20'"
                  " WHERE exhibition_id='3'")
    at = go_my(run())
    assert at.tabs[0].label == "전체"
    # 전체 탭: [관심](B전, A전) → [관람예정](C전) → [관람완료] 순으로 묶여 나온다
    assert [e.label.split(" · ")[0] for e in at.tabs[0].expander] == ["B전", "A전", "C전"]
    assert [e.label.split(" · ")[0] for e in at.tabs[1].expander] == ["B전", "A전"]
    assert [e.label.split(" · ")[0] for e in at.tabs[2].expander] == ["C전"]
    assert not at.tabs[3].expander


def test_ac8_tie_breaks_by_exhibition_id(env):
    db, _ = env
    repository.init_db(db)
    for i in ("2", "1"):
        repository.save(db, make(i, f"T{i}"))
    with sqlite3.connect(db) as c:
        c.execute("UPDATE saved_exhibition SET updated_at='2026-01-01T00:00:00'")
    assert [r["title"] for r in repository.list_by_status(db, "관심")] == ["T1", "T2"]
