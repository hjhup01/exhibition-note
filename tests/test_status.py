"""AC9: 상태·예정일 규칙 (repository 직접 호출, 오프라인)."""
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from exhibition_app import config, culture_api, messages, repository as repo
from exhibition_app.culture_api import Exhibition

TODAY = date(2026, 11, 11)
NOW = datetime(2026, 11, 11, 10, 0, 0)
LATER = datetime(2027, 1, 1, 9, 0, 0)
APP = str(Path(__file__).resolve().parent.parent / "src" / "app.py")


def ex(i="1"):
    return {"exhibition_id": i, "title": "전시", "category": "미술", "region": "서울",
            "place": "미술관", "start_date": "2026-11-01", "end_date": "2026-12-01"}


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "x.db")
    assert repo.init_db(path).ok
    assert repo.save(path, ex("1"), today=TODAY, now=NOW).ok
    return path


def raw(db):
    with sqlite3.connect(db) as c:
        return c.execute("SELECT * FROM saved_exhibition ORDER BY exhibition_id").fetchall()


def rejects(db, fn, msg):
    before = raw(db)
    r = fn()
    assert (r.ok, r.message) == (False, msg)
    assert raw(db) == before


def plan(db, d, now=NOW):
    return repo.plan(db, "1", d, today=TODAY, now=now)


def test_ac9_forward_flow_keeps_planned_date(db):
    assert plan(db, "2026-11-20").ok
    r = repo.list_by_status(db, "관람예정")[0]
    assert r["planned_visit_date"] == "2026-11-20" and r["updated_at"] == NOW.isoformat()
    assert repo.complete(db, "1", today=TODAY, now=LATER).ok
    r = repo.list_by_status(db, "관람완료")[0]
    assert r["planned_visit_date"] == "2026-11-20" and r["updated_at"] == LATER.isoformat()
    assert r["review_rating"] is None and r["review_text"] is None


def test_ac9_yesterday_accepted(db):
    y = (TODAY - timedelta(days=1)).isoformat()
    assert plan(db, y).ok
    assert repo.list_by_status(db, "관람예정")[0]["planned_visit_date"] == y


@pytest.mark.parametrize("bad", ["2026-02-30", "2026/12/01", "2026-1-5", "", None, 20261201])
def test_ac9_bad_dates_rejected(db, bad):
    rejects(db, lambda: plan(db, bad, LATER), messages.INVALID_PLANNED_DATE)
    assert plan(db, "2026-11-20").ok
    rejects(db, lambda: repo.change_planned_date(db, "1", bad, today=TODAY, now=LATER),
            messages.INVALID_PLANNED_DATE)


def test_ac9_interest_to_done_rejected(db):
    rejects(db, lambda: repo.complete(db, "1", today=TODAY, now=LATER), messages.INVALID_TRANSITION)


def test_ac9_no_going_back_or_skipping(db):
    assert plan(db, "2026-11-20").ok
    rejects(db, lambda: plan(db, "2026-11-21", LATER), messages.INVALID_TRANSITION)
    assert repo.complete(db, "1", today=TODAY, now=NOW).ok
    rejects(db, lambda: plan(db, "2026-11-21", LATER), messages.INVALID_TRANSITION)
    rejects(db, lambda: repo.complete(db, "1", today=TODAY, now=LATER), messages.INVALID_TRANSITION)


def test_ac9_change_date_only_when_planned(db):
    rejects(db, lambda: repo.change_planned_date(db, "1", "2026-11-25", today=TODAY, now=LATER),
            messages.PLANNED_DATE_STATE)
    assert plan(db, "2026-11-20").ok
    assert repo.change_planned_date(db, "1", "2026-11-25", today=TODAY, now=LATER).ok
    assert repo.list_by_status(db, "관람예정")[0]["planned_visit_date"] == "2026-11-25"
    assert repo.complete(db, "1", today=TODAY, now=LATER).ok
    rejects(db, lambda: repo.change_planned_date(db, "1", "2026-11-26", today=TODAY, now=LATER),
            messages.PLANNED_DATE_STATE)


def test_ac9_status_not_changed_by_time(db, tmp_path, monkeypatch):
    assert plan(db, "2026-11-12").ok
    future = TODAY + timedelta(days=30)
    before = raw(db)
    assert repo.list_by_status(db, "관람예정")[0]["status"] == "관람예정"
    assert raw(db) == before

    monkeypatch.setenv("DB_PATH", db)
    monkeypatch.setattr(config, "today_kst", lambda: future)
    monkeypatch.setattr(culture_api, "fetch_exhibitions", lambda *a, **k: [
        Exhibition("1", "전시", "미술", "서울", "미술관", "2026-11-01", "2026-12-01")])
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    assert not at.exception
    at.sidebar.radio[0].set_value(messages.PAGE_MY).run()
    assert not at.exception
    assert [r["status"] for r in repo.list_by_status(db, "관람예정")] == ["관람예정"]
    assert repo.list_by_status(db, "관람완료") == []
    assert raw(db) == before
