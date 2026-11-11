"""화면 표시 보정: 관련 글 제목의 마크다운 문자 이스케이프, 지역 이름 통일(서울시 → 서울)."""
import pytest

from exhibition_app import culture_api, filters, search_api


class FakeSt:
    def __init__(self):
        self.md = []

    def subheader(self, t):
        pass

    def write(self, t):
        pass

    def markdown(self, t):
        self.md.append(t)


@pytest.mark.parametrize("title", [
    "[Pocus 전시 해설] 국립현대미술관 《기술의 노스탤지어》",
    "하남역사박물관 <이성산성, 한강을 지배하다>",
    "직지문화축제: 9월 4일~6일 | 청주",
    "잔_당신을 담아온 잔의 이야기 *무료* $0",
    "#무료전시 #온라인전시",
])
def test_titles_with_markdown_chars_are_escaped(title):
    st = FakeSt()
    search_api.render_section(st, "웹문서", {"message": None, "items": [
        {"title": title, "link": "https://x.kr/a (1)", "pub_date": "2026-11-01"}]})
    line = st.md[0]
    # 제목의 서식 문자는 모두 백슬래시로 이스케이프되어 링크 글자 안에 그대로 남는다
    text_part = line[1:line.index("](")]
    unescaped = text_part.replace("\\", "")
    assert unescaped == title.replace("\\", "")
    for ch in "[]<>~|_*$#:":
        assert ch not in text_part.replace("\\" + ch, "")
    # 링크 주소의 공백·괄호는 인코딩되어 링크가 끊기지 않는다
    assert line.endswith("](https://x.kr/a%20%281%29) · 2026-11-01")


def test_plain_title_unchanged():
    assert search_api.md_escape("빛의 층위 2026") == "빛의 층위 2026"


@pytest.mark.parametrize("raw,expected", [
    ("서울", "서울"), ("서울시", "서울"), ("서울특별시", "서울"), (" 서울시 ", "서울"),
    ("전북특별자치도", "전북"), ("전라북도", "전북"), ("부산광역시", "부산"), ("경기도", "경기"),
    ("강원특별자치도", "강원"), ("제주특별자치도", "제주"), ("", ""), (None, ""), ("해외", "해외"),
])
def test_normalize_region(raw, expected):
    assert culture_api.normalize_region(raw) == expected


def test_seoul_and_seoulsi_merge_into_one_region_option():
    items = [{"seq": str(i), "title": f"T{i}", "realmName": "전시", "area": area, "place": "P",
              "startDate": "20261101", "endDate": "20261231"}
             for i, area in enumerate(["서울", "서울시", "서울특별시", "부산", "전북특별자치도"])]
    ex = [culture_api.normalize_item(it) for it in items]
    assert [e.region for e in ex] == ["서울", "서울", "서울", "부산", "전북"]
    assert filters.region_options(ex) == ["전체", "부산", "서울", "전북"]
