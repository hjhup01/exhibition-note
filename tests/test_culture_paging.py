"""실제 API 형태 반영: realm2 전시 분야, 페이지 나눠 받기, HTML 엔티티, 미술관·갤러리만 필터."""
from datetime import date

import pytest

from exhibition_app import config, culture_api, filters
from exhibition_app.culture_api import Exhibition

TODAY = date(2026, 11, 11)


def xml_page(n_items, start_seq):
    items = "".join(
        f"<item><serviceName>전시</serviceName><seq>{start_seq + i}</seq><title>T{start_seq + i}</title>"
        f"<startDate>20261101</startDate><endDate>20261231</endDate><place>P</place>"
        f"<realmName>전시</realmName><area>서울</area></item>" for i in range(n_items))
    return ("<response><header><resultCode>00</resultCode></header><body>"
            f"<items>{items}</items></body></response>")


class Resp:
    def __init__(self, text, status=200):
        self.text, self.status_code = text, status


def test_request_uses_realm2_exhibition_code_and_paging_params():
    calls = []

    def get(url, params=None, timeout=None):
        calls.append((url, dict(params), timeout))
        return Resp(xml_page(1, 1))

    culture_api.fetch_exhibitions(http_get=get, env={"CULTURE_API_KEY": "k"})
    url, params, timeout = calls[0]
    assert url.endswith("/B553457/cultureinfo/realm2")
    assert params["realmCode"] == "D000" and params["PageNo"] == 1
    assert params["numOfrows"] == config.CULTURE_PAGE_SIZE and timeout == 10


def test_fetches_next_pages_until_short_page(monkeypatch):
    monkeypatch.setattr(culture_api, "CULTURE_PAGE_SIZE", 3)
    pages = {1: xml_page(3, 1), 2: xml_page(3, 4), 3: xml_page(1, 7)}
    seen = []

    def get(url, params=None, timeout=None):
        seen.append(params["PageNo"])
        return Resp(pages[params["PageNo"]])

    ex = culture_api.fetch_exhibitions(http_get=get, env={})
    assert seen == [1, 2, 3]
    assert [e.exhibition_id for e in ex] == [str(i) for i in range(1, 8)]


def test_stops_at_max_pages(monkeypatch):
    monkeypatch.setattr(culture_api, "CULTURE_PAGE_SIZE", 2)
    seen = []

    def get(url, params=None, timeout=None):
        seen.append(params["PageNo"])
        return Resp(xml_page(2, params["PageNo"] * 10))

    culture_api.fetch_exhibitions(http_get=get, env={})
    assert len(seen) == culture_api.MAX_PAGES


def test_failure_on_later_page_is_failure(monkeypatch):
    monkeypatch.setattr(culture_api, "CULTURE_PAGE_SIZE", 1)

    def get(url, params=None, timeout=None):
        return Resp(xml_page(1, 1)) if params["PageNo"] == 1 else Resp("x", 500)

    with pytest.raises(culture_api.CultureApiError):
        culture_api.fetch_exhibitions(http_get=get, env={})


def test_only_exhibition_realm_kept_and_entities_unescaped():
    body = ("<response><body><items>"
            "<item><seq>1</seq><title>하남 &amp;lt;이성산성&amp;gt;</title><realmName>전시</realmName>"
            "<startDate>20261101</startDate><endDate>20261231</endDate><place>A &amp;amp; B 갤러리</place></item>"
            "<item><seq>2</seq><title>연극</title><realmName>연극</realmName>"
            "<startDate>20261101</startDate><endDate>20261231</endDate></item>"
            "</items></body></response>")
    ex = culture_api.parse_response(body)
    assert [(e.title, e.place, e.category) for e in ex] == [("하남 <이성산성>", "A & B 갤러리", "전시")]


@pytest.mark.parametrize("place,expected", [
    ("부산현대미술관", True), ("서촌 갤러리", True), ("Gallery Hyundai", True), ("국제화랑", True),
    ("한강아트센터", True), ("하남역사박물관", False), ("부산영화체험박물관", False), ("", False)])
def test_is_art_venue(place, expected):
    assert filters.is_art_venue(place) is expected


def test_art_only_filter_and_other_filters_combine():
    base = [Exhibition("1", "빛", "전시", "서울", "서울시립미술관", "2026-11-01", "2026-12-31"),
            Exhibition("2", "빛과 역사", "전시", "서울", "서울역사박물관", "2026-11-01", "2026-12-31"),
            Exhibition("3", "빛", "전시", "부산", "부산 갤러리", "2026-11-01", "2026-12-31")]
    assert [e.exhibition_id for e in filters.filter_exhibitions(base, TODAY)] == ["1", "2", "3"]
    assert [e.exhibition_id for e in filters.filter_exhibitions(base, TODAY, art_only=True)] == ["1", "3"]
    assert [e.exhibition_id for e in filters.filter_exhibitions(
        base, TODAY, region="서울", keyword="빛", art_only=True)] == ["1"]
