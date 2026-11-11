from datetime import date

from exhibition_app.culture_api import Exhibition
from exhibition_app import filters
from exhibition_app.filters import KEYWORD_MAX_LENGTH, base_set, filter_exhibitions, region_options

TODAY = date(2026, 11, 11)


def ex(i, title="전시", region="서울", start="2026-10-01", end="2026-12-31"):
    return Exhibition(str(i), title, "미술", region, "", start, end)


def ids(rows):
    return [r.exhibition_id for r in rows]


def test_ac2_ongoing_inclusive_bounds():
    rows = [ex(1, start="2026-11-11", end="2026-12-01"), ex(2, start="2026-10-01", end="2026-11-11"),
            ex(3, start="2026-11-12", end="2026-12-01"), ex(4, start="2026-10-01", end="2026-11-10")]
    assert ids(filter_exhibitions(base_set(rows, TODAY), TODAY, period="진행중")) == ["1", "2"]


def test_ac2_upcoming_includes_tomorrow_excludes_today():
    rows = [ex(1, start="2026-11-12", end="2026-12-01"), ex(2, start="2026-11-11", end="2026-12-01")]
    assert ids(filter_exhibitions(rows, TODAY, period="진행예정")) == ["1"]


def test_ac2_all_period_is_whole_base_set_and_excludes_ended():
    rows = [ex(1, start="2026-01-01", end="2026-01-02"), ex(2), ex(3, start="2026-12-01")]
    base = base_set(rows, TODAY)
    assert ids(filter_exhibitions(base, TODAY)) == ["2", "3"]


def test_ac2_region_options_sorted_unique_nonempty():
    rows = [ex(1, region="서울"), ex(2, region="부산"), ex(3, region=""), ex(4, region="서울")]
    assert region_options(rows) == ["전체", "부산", "서울"]
    assert region_options([]) == ["전체"]


def test_ac2_empty_region_only_in_all():
    rows = [ex(1, region=""), ex(2, region="서울")]
    assert ids(filter_exhibitions(rows, TODAY, region="전체")) == ["1", "2"]
    assert ids(filter_exhibitions(rows, TODAY, region="서울")) == ["2"]


def test_ac2_empty_keyword_no_reduction():
    rows = [ex(1), ex(2)]
    for kw in ["", "   ", None]:
        assert ids(filter_exhibitions(rows, TODAY, keyword=kw)) == ["1", "2"]


def test_ac2_keyword_trim_and_casefold():
    rows = [ex(1, title="mmca 특별전"), ex(2, title="피카소")]
    assert ids(filter_exhibitions(rows, TODAY, keyword="  MMCA  ")) == ["1"]


def test_ac2_keyword_only_first_50_codepoints():
    rows = [ex(1, title="가" * 50 + "나"), ex(2, title="가" * 50)]
    assert ids(filter_exhibitions(rows, TODAY, keyword="가" * 50 + "다" * 10)) == ["1", "2"]
    assert ids(filter_exhibitions(rows, TODAY, keyword=" " + "가" * 49 + " 나")) == ["1", "2"]
    assert ids(filter_exhibitions(rows, TODAY, keyword="나" * 60)) == []


def test_ac2_all_filters_and():
    rows = [ex(1, title="모네", region="서울"), ex(2, title="모네", region="부산"),
            ex(3, title="모네", region="서울", start="2026-12-01"), ex(4, title="고흐", region="서울")]
    assert ids(filter_exhibitions(rows, TODAY, "진행중", "서울", "모네")) == ["1"]


def test_ac2_keyword_max_length_constant_is_50_and_used():
    assert filters.KEYWORD_MAX_LENGTH == 50
    n = KEYWORD_MAX_LENGTH
    rows = [ex(1, title="가" * n)]
    assert ids(filter_exhibitions(rows, TODAY, keyword="가" * n + "다" * 10)) == ["1"]
