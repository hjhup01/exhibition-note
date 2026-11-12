"""점검 후 개선: 다시 불러오기, 상세 캐시(여러 전시), 정렬, 패키지 버전 고정, 휴대폰 배치."""
from datetime import date
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from exhibition_app import config, culture_api, filters, messages, search_api, summarizer
from exhibition_app.culture_api import Exhibition

ROOT = Path(__file__).resolve().parent.parent
APP = str(ROOT / "src" / "app.py")
TODAY = date(2026, 11, 12)
NOW = [
    Exhibition("1", "나 전시", "전시", "서울", "갤러리", "2026-11-01", "2026-12-31", "종로구"),
    Exhibition("2", "가 전시", "전시", "서울", "미술관", "2026-11-10", "2026-11-20", "중구"),
    Exhibition("3", "다 전시", "전시", "서울", "미술관", "2026-10-01", "2026-11-15", "중구"),
]


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "x.db"))
    monkeypatch.setattr(config, "today_kst", lambda: TODAY)
    monkeypatch.setattr(culture_api, "fetch_exhibitions", lambda *a, **k: list(NOW))
    calls = {"related": 0}
    empty = {"items": [], "message": messages.NO_RESULT, "failed": False}

    def related(*a, **k):
        calls["related"] += 1
        return {"web": dict(empty), "blogs": dict(empty)}

    monkeypatch.setattr(search_api, "load_related", related)
    monkeypatch.setattr(summarizer, "summarize", lambda *a, **k: "")
    monkeypatch.setattr(culture_api, "fetch_detail", lambda *a, **k: None)
    return calls


def titles(at):
    return [b.label for b in at.main.button if str(b.key).startswith("pick-")]


def test_retry_button_reloads_after_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "x.db"))
    monkeypatch.setattr(config, "today_kst", lambda: TODAY)
    state = {"fail": True}

    def fetch(*a, **k):
        if state["fail"]:
            raise culture_api.CultureApiError("down")
        return list(NOW)

    monkeypatch.setattr(culture_api, "fetch_exhibitions", fetch)
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert messages.CULTURE_FAILED in [m.value for m in at.main.markdown]
    state["fail"] = False  # API가 돌아옴
    at.button(key="retry-load").click().run()
    assert not at.exception
    assert len(titles(at)) == 3


def test_detail_cache_keeps_several_exhibitions(env):
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.button(key="pick-1").click().run()
    at.button(key="pick-2").click().run()
    at.button(key="pick-1").click().run()  # 다시 고르면 검색·요약을 다시 하지 않는다
    assert not at.exception
    assert env["related"] == 2
    assert set(at.session_state["detail_cache"]) == {"1", "2"}


def test_sort_exhibitions_orders():
    assert [e.exhibition_id for e in filters.sort_exhibitions(NOW, messages.SORT_DEFAULT)] == ["1", "2", "3"]
    assert [e.exhibition_id for e in filters.sort_exhibitions(NOW, messages.SORT_ENDING)] == ["3", "2", "1"]
    assert [e.exhibition_id for e in filters.sort_exhibitions(NOW, messages.SORT_NEWEST)] == ["2", "1", "3"]
    assert [e.exhibition_id for e in filters.sort_exhibitions(NOW, messages.SORT_TITLE)] == ["2", "1", "3"]


def test_sort_selectbox_changes_list_and_home_resets(env):
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert titles(at) == ["나 전시", "가 전시", "다 전시"]
    at.sidebar.selectbox(key="sort").set_value(messages.SORT_ENDING).run()
    assert titles(at) == ["다 전시", "가 전시", "나 전시"]
    at.sidebar.button(key="home").click().run()
    assert not at.exception and not at.warning
    assert at.sidebar.selectbox(key="sort").value == messages.SORT_DEFAULT


def test_requirements_are_pinned():
    lines = [ln.strip() for ln in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
             if ln.strip() and not ln.startswith("#")]
    assert all("==" in ln for ln in lines), lines


def test_mobile_layout_css_present():
    src = (ROOT / "src" / "app.py").read_text(encoding="utf-8")
    assert "@media (max-width: 640px)" in src


# ---------- 배치: 메뉴는 본문 위 탭 줄, 사이드바는 필터 카드 + 맨 아래 계정 카드 ----------

def test_page_menu_is_in_main_area_not_sidebar(env):
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert at.radio(key="page").value == messages.PAGE_FIND
    assert not at.sidebar.radio  # 사이드바에는 메뉴가 없다
    src = (ROOT / "src" / "app.py").read_text(encoding="utf-8")
    assert 'st.container(key="top-nav")' in src and "horizontal=True" in src


def test_filter_card_only_on_find_page_and_reset_button(env):
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert at.sidebar.selectbox(key="period") and at.sidebar.selectbox(key="sort")
    at.sidebar.selectbox(key="sort").set_value(messages.SORT_TITLE).run()
    at.sidebar.text_input(key="keyword").set_value("가").run()
    at.sidebar.button(key="reset-filters").click().run()
    assert not at.exception and not at.warning
    assert at.sidebar.selectbox(key="sort").value == messages.SORT_DEFAULT
    assert at.sidebar.text_input(key="keyword").value == ""
    at.radio(key="page").set_value(messages.PAGE_ASSISTANT).run()
    assert not [s for s in at.sidebar.selectbox if s.key == "period"]  # 다른 화면에는 필터가 없다


def test_logo_button_goes_home_from_any_page(env):
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.radio(key="page").set_value(messages.PAGE_MY).run()
    at.sidebar.button(key="home").click().run()
    assert at.radio(key="page").value == messages.PAGE_FIND
