"""추가 기능: 홈 버튼, 지난 전시(기간 선택), 전시중·전시예정 이름, 지역 여러 개·서울 구, 요금·주소·지도."""
from datetime import date
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from exhibition_app import config, culture_api, filters, messages, search_api, summarizer
from exhibition_app.culture_api import Exhibition, fetch_detail as real_fetch_detail

TODAY = date(2026, 11, 12)
APP = str(Path(__file__).resolve().parent.parent / "src" / "app.py")
NOW = [
    Exhibition("1", "종로 전시", "전시", "서울", "서울 갤러리", "2026-11-01", "2026-12-31", "종로구"),
    Exhibition("2", "강남 전시", "전시", "서울", "강남 미술관", "2026-11-01", "2026-12-31", "강남구"),
    Exhibition("3", "부산 전시", "전시", "부산", "부산 미술관", "2026-11-01", "2026-12-31", "해운대구"),
    Exhibition("4", "대구 전시", "전시", "대구", "대구 미술관", "2026-11-01", "2026-12-31", "중구"),
]
PAST = [
    Exhibition("9", "지난 종로 전시", "전시", "서울", "서울 갤러리", "2026-08-01", "2026-09-30", "종로구"),
    Exhibition("8", "아직 하는 전시", "전시", "서울", "P", "2026-08-01", "2026-12-31", "중구"),
]


class Resp:
    def __init__(self, text, status=200):
        self.text, self.status_code = text, status


# ---------- 데이터·필터 ----------

def test_district_parsed_from_sigungu():
    e = culture_api.normalize_item({"seq": "1", "title": "T", "realmName": "전시", "area": "서울", "sigungu": "종로구",
                                    "startDate": "20261101", "endDate": "20261231"})
    assert e.district == "종로구"


def test_multi_region_and_seoul_districts_filter():
    pick = lambda **kw: [e.exhibition_id for e in filters.filter_exhibitions(NOW, TODAY, **kw)]
    assert pick(region=["서울", "부산"]) == ["1", "2", "3"]
    assert pick(region=[]) == ["1", "2", "3", "4"]                         # 아무것도 안 고르면 전체
    assert pick(region=["서울", "부산"], districts={"서울": ["종로구"]}) == ["1", "3"]
    assert filters.district_options(NOW, "서울") == ["강남구", "종로구"]


def test_fetch_exhibitions_between_uses_period_api_and_pages():
    seen = []
    page = "<response><body><items>" + "".join(
        f"<item><seq>{i}</seq><title>T{i}</title><realmName>{'전시' if i % 2 else '연극'}</realmName>"
        f"<startDate>20250101</startDate><endDate>20250201</endDate></item>" for i in range(3)) + "</items></body></response>"

    def get(url, params=None, timeout=None):
        seen.append((url, params))
        return Resp(page)
    items, truncated = culture_api.fetch_exhibitions_between(date(2025, 1, 1), date(2025, 3, 31), http_get=get, env={})
    url, params = seen[0]
    assert url.endswith("/cultureinfo/period2") and params["from"] == "20250101" and params["to"] == "20250331"
    assert params["serviceTp"] == "A" and params["numOfrows"] == 1000
    assert [e.exhibition_id for e in items] == ["1"] and not truncated     # 전시만 남는다


def test_fetch_detail_parses_price_address_and_coordinates():
    xml = ("<response><body><items><item><seq>1</seq><price>무료</price><placeAddr>부산광역시 사하구 낙동남로 1191</placeAddr>"
           "<phone>051-220-7400</phone><url>https://x.kr/e</url><gpsX>128.94</gpsX><gpsY>35.10</gpsY></item></items></body></response>")
    d = real_fetch_detail("1", http_get=lambda *a, **k: Resp(xml), env={})
    assert d["price"] == "무료" and d["address"].startswith("부산광역시") and (d["lat"], d["lon"]) == (35.10, 128.94)
    assert real_fetch_detail("1", http_get=lambda *a, **k: Resp("x", 500), env={}) is None
    bad = xml.replace("<gpsX>128.94</gpsX>", "<gpsX>0</gpsX>")
    assert real_fetch_detail("1", http_get=lambda *a, **k: Resp(bad), env={})["lat"] is None   # 국외·잘못된 좌표는 지도에서 뺀다


# ---------- 화면 ----------

@pytest.fixture
def app_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "x.db"))
    monkeypatch.setattr(config, "today_kst", lambda: TODAY)
    monkeypatch.setattr(culture_api, "fetch_exhibitions", lambda *a, **k: list(NOW))
    calls = []
    monkeypatch.setattr(culture_api, "fetch_exhibitions_between",
                        lambda s, e, **k: calls.append((s, e)) or (list(PAST), False))
    empty = {"items": [], "message": messages.NO_RESULT, "failed": False}
    monkeypatch.setattr(search_api, "load_related", lambda *a, **k: {"web": dict(empty), "blogs": dict(empty)})
    monkeypatch.setattr(summarizer, "summarize", lambda *a, **k: "")
    return calls


def titles(at):
    return [b.label.removeprefix("▶ ") for b in at.main.button]


def pane_titles(at):
    return " ".join(h.proto.body for h in at.get("html"))


def test_period_labels_renamed():
    assert (messages.PERIOD_ONGOING, messages.PERIOD_UPCOMING, messages.PERIOD_PAST) == ("전시중", "전시예정", "지난 전시")


def test_region_multiselect_and_seoul_district(app_env):
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert titles(at) == ["종로 전시", "강남 전시"]
    at.sidebar.multiselect(key="regions").set_value(["서울", "부산"]).run()
    assert titles(at) == ["종로 전시", "강남 전시", "부산 전시"]
    at.sidebar.multiselect(key="districts-서울").set_value(["종로구"]).run()
    assert titles(at) == ["종로 전시", "부산 전시"]
    assert "서울(종로구)·부산 - 전시중인 목록" in pane_titles(at)


def test_past_exhibitions_with_date_range(app_env):
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.sidebar.selectbox(key="period").set_value("지난 전시").run()
    assert not at.exception
    assert titles(at) == ["지난 종로 전시"]                      # 아직 끝나지 않은 전시는 빠진다
    assert "종료" in " ".join(c.value for c in at.main.caption)
    s, e = app_env[-1]
    assert (TODAY - s).days == 90 and (TODAY - e).days == 1
    at.sidebar.date_input(key="past-range").set_value((date(2026, 9, 1), date(2026, 9, 30))).run()
    assert app_env[-1] == (date(2026, 9, 1), date(2026, 9, 30))
    assert "서울 - 지난 전시 목록 (2026-09-01 ~ 2026-09-30)" in pane_titles(at)


def test_home_button_resets_page_and_filters(app_env):
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.sidebar.multiselect(key="regions").set_value(["부산"]).run()
    at.sidebar.selectbox(key="period").set_value("전체").run()
    at.button(key="pick-3").click().run()
    at.sidebar.radio[0].set_value(messages.PAGE_MY).run()
    at.sidebar.button(key="home").click().run()
    assert not at.exception
    assert at.sidebar.radio[0].value == messages.PAGE_FIND
    assert at.sidebar.selectbox(key="period").value == "전시중"
    assert at.sidebar.multiselect(key="regions").value == ["서울"]
    assert messages.SELECT_EXHIBITION in [m.value for m in at.main.markdown]


def test_detail_shows_price_address_link_and_map(app_env, monkeypatch):
    monkeypatch.setattr(culture_api, "fetch_detail", lambda eid, **k: {
        "price": "성인 5,000원", "address": "서울특별시 종로구 삼청로 30", "phone": "02-000-0000",
        "url": "https://x.kr/e", "place_url": "", "lat": 37.58, "lon": 126.98})
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.button(key="pick-1").click().run()
    assert not at.exception
    texts = [m.value for m in at.main.markdown]
    assert "**요금** · 성인 5,000원" in texts and "**주소** · 서울특별시 종로구 삼청로 30" in texts
    assert "[전시 안내 페이지](https://x.kr/e)" in texts
    assert len(at.get("map")) == 1 or len(at.get("deck_gl_json_chart")) == 1


def test_detail_without_info_shows_notice(app_env):
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.button(key="pick-1").click().run()
    assert messages.DETAIL_NO_INFO in [c.value for c in at.main.caption]
