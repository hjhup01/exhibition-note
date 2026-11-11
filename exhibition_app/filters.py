"""기본 집합(종료되지 않은 전시)과 기간·지역·키워드 필터. 모두 AND."""
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
        if kw and kw not in e.title.casefold():
            continue
        out.append(e)
    return out
