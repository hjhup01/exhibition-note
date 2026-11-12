"""기본 집합(종료되지 않은 전시)과 기간·지역·키워드 필터. 모두 AND."""
import re
from datetime import date

from .messages import PERIOD_ALL, PERIOD_ONGOING, PERIOD_UPCOMING, REGION_ALL

KEYWORD_MAX_LENGTH = 50
# 장소 이름에 이 낱말이 들어 있으면 미술관·갤러리 전시로 본다(대소문자 무시).
ART_VENUE_WORDS = ("미술관", "갤러리", "화랑", "아트센터", "아트스페이스", "아트홀갤러리", "비엔날레",
                   "gallery", "art center", "museum of art", "mmca")


def is_art_venue(place) -> bool:
    p = (place or "").casefold()
    return any(w in p for w in ART_VENUE_WORDS)


def base_set(exhibitions, today: date) -> list:
    """end_date ≥ today인 전시."""
    t = today.isoformat()
    return [e for e in exhibitions if e.end_date >= t]


def region_options(base) -> list:
    return [REGION_ALL] + sorted({e.region for e in base if e.region})


def normalize_keyword(keyword) -> str:
    return (keyword or "").strip()[:KEYWORD_MAX_LENGTH].strip().casefold()


def _compact(text):
    """문장부호·공백을 뺀 소문자 문자열(예: '패트릭 블랑: 수직정원' → '패트릭블랑수직정원')."""
    return re.sub(r"[^0-9a-z가-힣]", "", (text or "").casefold())


def keyword_matches(kw, title) -> bool:
    """정규화된 키워드가 제목에 그대로 있거나, 문장부호를 무시했을 때 키워드의 낱말이 모두 제목에 있으면 True.
    예: '패트릭 블랑 수직정원'은 '패트릭 블랑: 수직정원'과 일치한다."""
    if not kw:
        return True
    if kw in (title or "").casefold():
        return True
    t = _compact(title)
    words = [_compact(w) for w in kw.split()]
    return any(words) and all(w in t for w in words if w)


def filter_exhibitions(base, today: date, period=PERIOD_ALL, region=REGION_ALL, keyword="",
                       art_only=False) -> list:
    t = today.isoformat()
    kw = normalize_keyword(keyword)
    out = []
    for e in base:
        if art_only and not is_art_venue(e.place):
            continue
        if period == PERIOD_ONGOING and not (e.start_date <= t <= e.end_date):
            continue
        if period == PERIOD_UPCOMING and not e.start_date > t:
            continue
        if region != REGION_ALL and e.region != region:
            continue
        if kw and not keyword_matches(kw, e.title):
            continue
        out.append(e)
    return out
