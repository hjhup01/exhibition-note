"""AC: 전시 목록 화면 - 내용 (가짜 문화포털 응답, 고정 today)."""
import datetime
import json
import pathlib

import pytest
from streamlit.testing.v1 import AppTest

from exhibition_app import config, culture_api

APP = str(pathlib.Path(__file__).resolve().parent.parent / "app.py")
TODAY = datetime.date(2026, 11, 11)


def item(**kw):
    base = {"seq": "1", "title": "전시", "realmName": "전시", "area": "서울", "place": "미술관",
            "startDate": "20261001", "endDate": "20261231"}
    base.update(kw)
    return {k: v for k, v in base.items() if v is not ...}


def envelope(items):
    return json.dumps({"response": {"body": {"items": {"item": items}}}})


def run_app(monkeypatch, items):
    monkeypatch.setattr(config, "today_kst", lambda: TODAY)
    monkeypatch.setattr(culture_api, "fetch_exhibitions",
                        lambda *a, **k: culture_api.parse_response(envelope(items)))
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    return at


def shown_titles(at):
    return [b.label.removeprefix("▶ ") for b in at.button]


EXCLUDED = [
    item(title="카테고리공백", realmName="전시 "),
    item(title="연극", realmName="연극"),
    item(title="seq없음", seq=...),
    item(title="seq공백", seq="  "),
    item(title="seq불리언", seq=True),
    item(title="seq실수", seq=1.5),
    item(title="seq널", seq=None),
    item(title="", seq="2"),
    item(title="  ", seq="3"),
    item(title=None, seq="4"),
    item(title="시작없음", seq="5", startDate=...),
    item(title="종료널", seq="6", endDate=None),
    item(title="날짜실수", seq="7", startDate=20261001.0),
    item(title="날짜불리언", seq="8", endDate=True),
    item(title="날짜없는달력", seq="9", startDate="20260230"),
    item(title="날짜7자리", seq="10", startDate="2026101"),
    item(title="날짜하이픈", seq="11", startDate="2026-10-01"),
    item(title="시작>종료", seq="12", startDate="20261201", endDate="20261101"),
    item(title="종료됨", seq="13", startDate="20260101", endDate="20261110"),
]


def test_ac1_only_valid_unended_art_exhibitions_shown(monkeypatch):
    good = [
        item(title="정상", seq="100"),
        item(title="정수seq", seq=12345),
        item(title="정수날짜", seq="200", startDate=20261111, endDate=20261111),
        item(title="지역장소없음", seq="300", area=..., place=...),
    ]
    at = run_app(monkeypatch, EXCLUDED + good)
    # 첫 화면 기본 필터는 진행중·서울이라 지역이 빈 전시는 지역 '전체'에서만 보인다
    assert shown_titles(at) == ["정상", "정수seq", "정수날짜"]
    at.sidebar.selectbox(key="region").set_value("전체").run()
    assert shown_titles(at) == ["정상", "정수seq", "정수날짜", "지역장소없음"]


def test_first_screen_defaults_to_ongoing_and_seoul(monkeypatch):
    at = run_app(monkeypatch, [
        item(title="서울진행", seq="1"),
        item(title="부산진행", seq="2", area="부산"),
        item(title="서울예정", seq="3", startDate="20261201", endDate="20261231"),
    ])
    assert at.sidebar.selectbox(key="period").value == "진행중"
    assert at.sidebar.selectbox(key="region").value == "서울"
    assert shown_titles(at) == ["서울진행"]
    at.sidebar.selectbox(key="period").set_value("전체").run()
    at.sidebar.selectbox(key="region").set_value("전체").run()
    assert shown_titles(at) == ["서울진행", "부산진행", "서울예정"]


def test_region_default_falls_back_to_all_when_no_seoul(monkeypatch):
    at = run_app(monkeypatch, [item(title="부산진행", seq="2", area="부산")])
    assert at.sidebar.selectbox(key="region").value == "전체"
    assert shown_titles(at) == ["부산진행"]


def test_ac1_int_seq_normalized_and_missing_area_place_blank():
    e = culture_api.parse_response(envelope([item(seq=12345, area=..., place=...)]))[0]
    assert e.exhibition_id == "12345" and e.region == "" and e.place == ""
    e = culture_api.parse_response(envelope([item(startDate=20261111, endDate=20261112)]))[0]
    assert (e.start_date, e.end_date) == ("2026-11-11", "2026-11-12")


@pytest.mark.parametrize("bad", [item(seq=True), item(seq=1.5), item(realmName="전시 "),
                                 item(startDate="20260230"), item(startDate="20261201", endDate="20261101")])
def test_ac1_invalid_items_dropped_by_parser(bad):
    assert culture_api.parse_response(envelope([bad])) == []


def test_ac1_xml_response_and_envelope_rules():
    xml = ("<response><body><items><item><seq>5</seq><title>A</title><realmName>전시</realmName>"
           "<startDate>20261001</startDate><endDate>20261002</endDate></item></items></body></response>")
    assert [e.exhibition_id for e in culture_api.parse_response(xml)] == ["5"]
    assert culture_api.parse_response("<response><body><items/></body></response>") == []
    assert culture_api.parse_response('{"response":{"body":{"items":""}}}') == []
    for raw in ["nope", "{}", '{"response":{"body":{}}}',
                '{"response":{"body":{"items":{"item":{"seq":1}}}}}']:
        with pytest.raises(culture_api.CultureApiError):
            culture_api.parse_response(raw)
