"""내 전시 화면 조작 흐름 (AppTest): 저장 → 관람예정 지정 → 예정일 변경 → 관람완료 → 관람평 작성·수정·삭제 → 기록 삭제.
외부 호출은 모두 가짜로 바꾸고, 저장 결과는 SQLite 행으로 확인한다."""
import sqlite3
from datetime import date
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from exhibition_app import config, culture_api, messages, repository, search_api, summarizer
from exhibition_app.culture_api import Exhibition

TODAY = date(2026, 11, 11)
APP = str(Path(__file__).resolve().parent.parent / "src" / "app.py")


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = str(tmp_path / "x.db")
    monkeypatch.setenv("DB_PATH", path)
    monkeypatch.setattr(config, "today_kst", lambda: TODAY)
    monkeypatch.setattr(culture_api, "fetch_exhibitions", lambda *a, **k: [
        Exhibition("1", "빛의 층위", "미술", "서울", "한강아트센터", "2026-10-02", "2027-01-18")])
    empty = {"items": [], "message": messages.NO_RESULT}
    monkeypatch.setattr(search_api, "load_related", lambda *a, **k: {"web": dict(empty), "blogs": dict(empty)})
    monkeypatch.setattr(summarizer, "summarize", lambda *a, **k: None)
    return path


def row(db):
    with sqlite3.connect(db) as c:
        c.row_factory = sqlite3.Row
        r = c.execute("SELECT * FROM saved_exhibition WHERE exhibition_id='1'").fetchone()
    return dict(r) if r else None


def texts(at):
    return [m.value for m in at.markdown] + [c.value for c in at.caption]


def start_saved_on_my_page():
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.button(key="pick-1").click().run()
    at.button(key="save-1").click().run()
    assert messages.SAVED_DONE in texts(at)
    at.radio(key="page").set_value(messages.PAGE_MY).run()
    assert not at.exception
    return at


def test_full_flow_plan_change_complete_review(db):
    at = start_saved_on_my_page()
    assert row(db)["status"] == "관심"

    # 관심 → 관람예정 (과거 날짜 허용)
    at.date_input(key="plan-date-1").set_value(date(2026, 11, 10)).run()
    at.button(key="plan-1").click().run()
    assert not at.exception
    assert messages.PLANNED_DONE in texts(at)
    assert (row(db)["status"], row(db)["planned_visit_date"]) == ("관람예정", "2026-11-10")

    # 예정일 변경
    at.date_input(key="change-date-1").set_value(date(2026, 11, 22)).run()
    at.button(key="change-1").click().run()
    assert row(db)["planned_visit_date"] == "2026-11-22"

    # 관람예정 → 관람완료 (예정일 유지, 관람평은 비어 있음)
    at.button(key="done-1").click().run()
    r = row(db)
    assert (r["status"], r["planned_visit_date"], r["review_rating"], r["review_text"]) == \
        ("관람완료", "2026-11-22", None, None)
    assert messages.NO_REVIEW in texts(at)

    # 관람평 작성 → 수정
    at.radio(key="rating-1").set_value(4).run()
    at.text_area(key="review-text-1").input("  자연광 전시실이 좋았다.  ").run()
    at.button(key="review-1").click().run()
    assert (row(db)["review_rating"], row(db)["review_text"]) == (4, "자연광 전시실이 좋았다.")
    assert messages.REVIEW_SAVED_DONE in texts(at)
    at.radio(key="rating-1").set_value(5).run()
    at.text_area(key="review-text-1").input("두 번째 관람, 더 좋았다.").run()
    at.button(key="review-1").click().run()
    assert (row(db)["review_rating"], row(db)["review_text"]) == (5, "두 번째 관람, 더 좋았다.")

    # 저장된 관람평은 입력란에만 한 번 보인다(별도 표시 없음)
    assert "★★★★★" not in [m.value for m in at.tabs[3].markdown]
    assert at.text_area(key="review-text-1").value == "두 번째 관람, 더 좋았다."

    # 관람평 삭제: 한 번 더 묻고 → 취소하면 그대로
    at.button(key="review-del-1").click().run()
    assert messages.REVIEW_DELETE_CONFIRM in [w.value for w in at.warning]
    assert row(db)["review_rating"] == 5
    at.button(key="review-del-1-no").click().run()
    assert not at.warning and row(db)["review_rating"] == 5

    # 다시 삭제 → 확인: 별점·텍스트만 비고 관람완료 탭에 남으며, 입력란도 비워진다
    at.button(key="review-del-1").click().run()
    at.button(key="review-del-1-yes").click().run()
    assert not at.exception and not at.warning
    assert messages.REVIEW_DELETED_DONE in texts(at)
    assert at.text_area(key="review-text-1").value == "" and at.radio(key="rating-1").value == 5
    r = row(db)
    assert (r["status"], r["review_rating"], r["review_text"]) == ("관람완료", None, None)
    assert "빛의 층위" in [e.label.split(" · ")[0] for e in at.tabs[3].expander]  # 0=전체, 3=관람완료

    # 전시 기록 삭제: 한 번 더 묻고(취소하면 그대로) → 확인하면 지운다
    at.button(key="del-1").click().run()
    assert any("기록을 삭제할까요?" in w.value for w in at.warning) and row(db) is not None
    at.button(key="del-1-no").click().run()
    assert row(db) is not None and not at.warning
    at.button(key="del-1").click().run()
    at.button(key="del-1-yes").click().run()
    assert not at.exception
    assert row(db) is None
    assert messages.RECORD_DELETED_DONE in texts(at)


def test_blank_review_rejected_and_row_unchanged(db):
    at = start_saved_on_my_page()
    at.button(key="plan-1").click().run()
    at.button(key="done-1").click().run()
    before = row(db)
    at.text_area(key="review-text-1").input("   ").run()
    at.button(key="review-1").click().run()
    assert not at.exception
    assert messages.INVALID_REVIEW_TEXT in texts(at)
    assert row(db) == before


def test_controls_match_status(db):
    """관심 탭에는 예정 지정만, 관람완료 탭에만 관람평 입력이 보인다(되돌리기 버튼 없음)."""
    at = start_saved_on_my_page()
    keys = {b.key for b in at.button}
    assert {"plan-1", "del-1"} <= keys
    assert not keys & {"done-1", "change-1", "review-1"}
    assert not at.text_area
    at.button(key="plan-1").click().run()
    keys = {b.key for b in at.button}
    assert {"change-1", "done-1", "del-1"} <= keys and "plan-1" not in keys
    at.button(key="done-1").click().run()
    keys = {b.key for b in at.button}
    assert {"review-1", "del-1"} <= keys
    assert not keys & {"plan-1", "change-1", "done-1"}


def test_all_tab_first_lists_every_status_read_only(db, monkeypatch):
    monkeypatch.setattr(culture_api, "fetch_exhibitions", lambda *a, **k: [
        Exhibition("1", "빛의 층위", "미술", "서울", "한강아트센터", "2026-10-02", "2027-01-18"),
        Exhibition("2", "돌과 숨", "미술", "서울", "바다미술관", "2026-09-12", "2027-02-02")])
    repository.init_db(db)
    for e in culture_api.fetch_exhibitions():
        repository.save(db, e)
    repository.plan(db, "2", "2026-11-05")
    repository.complete(db, "2", "2026-11-05", today=TODAY)
    repository.write_review(db, "2", 4, "좋았다")
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.radio(key="page").set_value(messages.PAGE_MY).run()
    assert not at.exception
    assert [t.label for t in at.tabs] == ["전체", "관심", "관람예정", "관람완료"]
    all_tab = at.tabs[0]
    # 상태별 제목 아래에 목록: [관심] 빛의 층위 → [관람예정] 없음 → [관람완료] 돌과 숨
    heads = [b.label for b in all_tab.button]  # 묶음 제목은 누르면 그 탭으로 가는 버튼
    assert heads == ["[관심] · 1건  ›", "[관람예정] · 0건  ›", "[관람완료] · 1건  ›"]
    assert [s.value for s in all_tab.subheader] == ["빛의 층위", "돌과 숨"]
    captions = " ".join(c.value for c in all_tab.caption)
    assert "실제 관람일 2026-11-05" in captions and messages.EMPTY_TAB in captions
    assert "상태 관심" not in captions
    assert "★★★★☆" in [m.value for m in all_tab.markdown]
    assert len(all_tab.button) == 3 and len(all_tab.date_input) == 0  # 묶음 제목 버튼만(모아 보기 전용)
    # 본문의 [관람완료] 제목을 누르면 관람완료 탭이 열린다
    all_tab.button(key="goto-관람완료").click().run()
    assert not at.exception
    assert at.session_state["my-tab"] == "관람완료"
