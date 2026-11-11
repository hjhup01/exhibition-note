"""AC 4: 전시 상세 - 관련 글(카카오 웹문서·블로그). 가짜 HTTP 함수로 검증한다."""
import pytest
import requests

from exhibition_app import messages, search_api
from exhibition_app.search_api import (MSG_EMPTY, MSG_FAILED, RelatedApiError, fetch_related,
                                       load_related, load_section, parse_related, render_related)


class Resp:
    def __init__(self, payload=None, status=200, bad_json=False):
        self.payload, self.status_code, self.bad_json = payload, status, bad_json

    def json(self):
        if self.bad_json:
            raise ValueError("bad")
        return self.payload


def doc(title="t", url="http://a", dt="2026-11-02T10:00:00.000+09:00", contents="d"):
    d = {"title": title, "url": url, "datetime": dt, "contents": contents}
    return {k: v for k, v in d.items() if v is not ...}


def day(n):
    return f"2026-11-{n:02d}T10:00:00.000+09:00"


class FakeSt:
    def __init__(self):
        self.out = []

    def subheader(self, t):
        self.out.append(("h", t))

    def write(self, t):
        self.out.append(("w", t))

    def markdown(self, t):
        self.out.append(("m", t))


def test_ac4_html_removed_entities_decoded_and_dates_converted():
    n = parse_related({"documents": [doc(title="<b>모네</b> &amp; 전")]})[0]
    assert n == {"title": "모네 & 전", "link": "http://a", "pub_date": "2026-11-02", "description": "d"}
    b = parse_related({"documents": [doc(title="<b>x</b>", contents="<b>y</b>&quot;")]})[0]
    assert b["title"] == "x" and b["description"] == 'y"'


def test_ac4_datetime_converted_to_seoul_date():
    # UTC 16:00 = 서울 다음 날 01:00
    assert parse_related({"documents": [doc(dt="2026-11-02T16:00:00.000+00:00")]})[0]["pub_date"] == "2026-11-03"


def test_ac4_sorted_desc_max_five_ties_keep_order():
    docs = [doc(title=f"n{i}", dt=day(d)) for i, d in enumerate([1, 5, 3, 5, 2, 4, 6])]
    assert [g["title"] for g in parse_related({"documents": docs})] == ["n6", "n1", "n3", "n5", "n2"]
    docs = [doc(title=f"b{i}", dt=day(5)) for i in range(7)]
    assert [g["title"] for g in parse_related({"documents": docs})] == [f"b{i}" for i in range(5)]


def test_ac4_invalid_items_skipped():
    docs = [doc(title=...), doc(title="  "), doc(title="<b></b>"), doc(url=...), doc(url=" "),
            doc(dt="garbage"), doc(dt=""), doc(dt=...), "x", None, doc(title="ok")]
    assert [g["title"] for g in parse_related({"documents": docs})] == ["ok"]


def test_ac4_skipped_items_do_not_use_up_the_five():
    docs = [doc(url=...)] * 3 + [doc(title=f"n{i}") for i in range(6)]
    assert len(parse_related({"documents": docs})) == 5


@pytest.mark.parametrize("payload", [None, [], {}, {"documents": "x"}, {"documents": {}}])
def test_ac4_bad_payload_raises(payload):
    with pytest.raises(RelatedApiError):
        parse_related(payload)


def test_ac4_request_url_params_auth_and_timeout():
    calls = []

    def get(url, **kw):
        calls.append((url, kw))
        return Resp({"documents": []})

    fetch_related("web", "모네전", get=get, env={"KAKAO_REST_API_KEY": "REST"})
    fetch_related("blog", "모네전", get=get, env={"KAKAO_REST_API_KEY": "REST"})
    assert calls[0][0] == search_api.WEB_URL == "https://dapi.kakao.com/v2/search/web"
    assert calls[1][0] == search_api.BLOG_URL == "https://dapi.kakao.com/v2/search/blog"
    for _, kw in calls:
        assert kw["params"] == {"query": "모네전", "sort": "accuracy", "size": 10}
        assert kw["headers"] == {"Authorization": "KakaoAK REST"}
        assert kw["timeout"] == 10


def test_ac4_query_is_title_plus_place():
    queries = []

    def get(url, **kw):
        queries.append(kw["params"]["query"])
        return Resp({"documents": []})

    load_related("패트릭 블랑: 수직정원", place="부산현대미술관", get=get, env={})
    load_related(" 모네전 ", place="  ", get=get, env={})
    assert queries == ["패트릭 블랑: 수직정원 부산현대미술관"] * 2 + ["모네전"] * 2


def test_ac4_accuracy_results_still_shown_newest_first():
    docs = [doc(title="old", dt=day(1)), doc(title="new", dt=day(9)), doc(title="mid", dt=day(5))]
    assert [g["title"] for g in parse_related({"documents": docs})] == ["new", "mid", "old"]


@pytest.mark.parametrize("make", [
    lambda: (_ for _ in ()).throw(requests.Timeout()),
    lambda: Resp(status=401),
    lambda: Resp(status=500),
    lambda: Resp(bad_json=True),
    lambda: Resp({"nope": 1}),
])
def test_ac4_failures_become_message_not_exception(make):
    sec = load_section("web", "q", get=lambda url, **kw: make(), env={})
    assert sec["message"] == MSG_FAILED and sec["items"] == [] and sec["failed"]


def test_ac4_one_area_fails_other_normal_and_rendered():
    def get(url, **kw):
        if url == search_api.WEB_URL:
            raise requests.Timeout()
        return Resp({"documents": [doc(title="<b>글</b>", url="http://b")]})

    st = FakeSt()
    render_related(st, load_related("q", get=get, env={}))
    assert st.out == [("h", messages.WEB_HEADING), ("w", MSG_FAILED), ("h", messages.BLOG_HEADING),
                      ("m", "[글](http://b) · 2026-11-02")]


def test_ac4_empty_area_shows_no_result_and_description_hidden():
    def get(url, **kw):
        return Resp({"documents": []} if url == search_api.BLOG_URL else {"documents": [doc()]})

    st = FakeSt()
    render_related(st, load_related("q", get=get, env={}))
    assert ("w", MSG_EMPTY) in st.out and ("w", MSG_FAILED) not in st.out
    assert ("m", "[t](http://a) · 2026-11-02") in st.out
    assert not any(v == "d" for _, v in st.out)


def test_ac4_both_failed_and_both_empty():
    def boom(url, **kw):
        raise requests.ConnectionError()

    rel = load_related("q", get=boom, env={})
    assert rel["web"]["message"] == rel["blogs"]["message"] == MSG_FAILED
    rel = load_related("q", get=lambda u, **kw: Resp({"documents": []}), env={})
    assert rel["web"]["message"] == rel["blogs"]["message"] == MSG_EMPTY


def test_ac4_reopen_fetches_fresh_results():
    state = {"n": 0}

    def get(url, **kw):
        state["n"] += 1
        return Resp({"documents": [doc(title=f"v{state['n']}")]})

    first = load_related("q", get=get, env={})
    second = load_related("q", get=get, env={})
    assert first["web"]["items"][0]["title"] != second["web"]["items"][0]["title"]
    assert state["n"] == 4


def test_ac4_error_message_has_no_key():
    def get(url, **kw):
        raise RuntimeError(kw["headers"]["Authorization"])

    with pytest.raises(RelatedApiError) as e:
        fetch_related("web", "q", get=get, env={"KAKAO_REST_API_KEY": "SECRETVAL"})
    assert "SECRETVAL" not in str(e.value)
