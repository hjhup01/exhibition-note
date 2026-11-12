"""문화포털 '한눈에보는문화정보'(한국문화정보원_한눈에보는문화정보조회서비스) 요청·응답 해석·항목 정규화.

실제 응답의 분야(realmName)에는 '미술'이 없고 전시는 모두 '전시'로 온다(2026-11 확인).
그래서 분야가 '전시'인 항목 전체를 대상으로 하고, 미술관·갤러리 여부는 filters.is_art_venue로 고른다.
"""
import html
import json
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date

from .config import CULTURE_PAGE_SIZE, TIMEOUT_SECONDS

CULTURE_URL = "https://apis.data.go.kr/B553457/cultureinfo/realm2"
REALM_CODE_EXHIBITION = "D000"
EXHIBITION_CATEGORY = "전시"
ART_CATEGORY = EXHIBITION_CATEGORY  # 이전 이름 호환
MAX_PAGES = 10
_DATE_RE = re.compile(r"\d{8}", re.ASCII)


class CultureApiError(Exception):
    """응답을 해석할 수 없거나 호출에 실패했을 때. 메시지에 키·URL을 담지 않는다."""


@dataclass(frozen=True)
class Exhibition:
    exhibition_id: str
    title: str
    category: str
    region: str
    place: str
    start_date: str  # YYYY-MM-DD
    end_date: str
    district: str = ""  # 시·군·구(문화포털 sigungu). 예: 종로구


def _required_text(value):
    """str 또는 int(bool 제외)만 허용. strip 후 비어 있으면 None."""
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    text = str(value).strip()
    return text or None


def _date_text(value):
    text = _required_text(value)
    if text is None or not _DATE_RE.fullmatch(text):
        return None
    try:
        return date(int(text[:4]), int(text[4:6]), int(text[6:])).isoformat()
    except ValueError:
        return None


def _optional_text(value) -> str:
    return html.unescape(value).strip() if isinstance(value, str) else ""


# 문화포털 area는 대부분 짧은 이름('서울')이지만 '서울시'·'전북특별자치도'처럼 긴 이름도 섞여 온다(2026-11-11 확인).
# 필터에서 한 지역이 둘로 나뉘지 않도록 짧은 이름으로 통일한다.
_REGION_ALIASES = {
    "서울": ("서울시", "서울특별시"),
    "부산": ("부산시", "부산광역시"),
    "대구": ("대구시", "대구광역시"),
    "인천": ("인천시", "인천광역시"),
    "광주": ("광주시", "광주광역시"),
    "대전": ("대전시", "대전광역시"),
    "울산": ("울산시", "울산광역시"),
    "세종": ("세종시", "세종특별자치시"),
    "경기": ("경기도",),
    "강원": ("강원도", "강원특별자치도"),
    "충북": ("충청북도",),
    "충남": ("충청남도",),
    "전북": ("전라북도", "전북특별자치도"),
    "전남": ("전라남도",),
    "경북": ("경상북도",),
    "경남": ("경상남도",),
    "제주": ("제주도", "제주특별자치도"),
}
_REGION_MAP = {alias: short for short, aliases in _REGION_ALIASES.items() for alias in aliases}


def normalize_region(value) -> str:
    """'서울시'·'서울특별시' → '서울'처럼 시·도 이름을 짧은 이름으로 통일한다. 모르는 값은 그대로."""
    text = _optional_text(value).replace(" ", "")
    return _REGION_MAP.get(text, text)


def normalize_item(item):
    """원본 항목 하나를 Exhibition으로 바꾼다. 전시가 아니거나 건너뛸 항목이면 None.
    제목·장소의 HTML 엔티티(예: &lt;)는 풀어서 쓴다."""
    if not isinstance(item, dict) or item.get("realmName") != EXHIBITION_CATEGORY:
        return None
    exhibition_id = _required_text(item.get("seq"))
    title = _required_text(item.get("title"))
    title = html.unescape(title).strip() or None if title else None
    start = _date_text(item.get("startDate"))
    end = _date_text(item.get("endDate"))
    if not (exhibition_id and title and start and end) or start > end:
        return None
    return Exhibition(exhibition_id, title, EXHIBITION_CATEGORY,
                      normalize_region(item.get("area")), _optional_text(item.get("place")),
                      start, end, _optional_text(item.get("sigungu")))


def _json_items(data):
    body = data.get("response") if isinstance(data, dict) else None
    body = body.get("body") if isinstance(body, dict) else None
    if not isinstance(body, dict) or "items" not in body:
        raise CultureApiError("missing envelope")
    items = body["items"]
    if not items:
        return []
    if not isinstance(items, dict):
        raise CultureApiError("bad items")
    if "item" not in items:
        return []
    if not isinstance(items["item"], list):
        raise CultureApiError("item is not an array")
    return items["item"]


def _xml_items(text):
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        raise CultureApiError("not json or xml") from None
    if root.tag != "response":
        raise CultureApiError("missing envelope")
    body = root.find("body")
    items = body.find("items") if body is not None else None
    if items is None:
        raise CultureApiError("missing envelope")
    return [{child.tag: (child.text or "") for child in el} for el in items.findall("item")]


def _raw_items(text) -> list:
    if isinstance(text, bytes):
        text = text.decode("utf-8", errors="replace")
    if not isinstance(text, str):
        raise CultureApiError("bad body")
    try:
        data = json.loads(text)
    except ValueError:
        return _xml_items(text.strip())
    return _json_items(data)


def parse_response(text) -> list:
    """응답 본문(JSON 또는 XML)에서 유효한 전시를 모두 뽑는다. 실패하면 CultureApiError."""
    return [e for e in map(normalize_item, _raw_items(text)) if e]


def _get_page(http_get, key, page):
    params = {"serviceKey": key, "PageNo": page, "numOfrows": CULTURE_PAGE_SIZE,
              "realmCode": REALM_CODE_EXHIBITION}
    try:
        resp = http_get(CULTURE_URL, params=params, timeout=TIMEOUT_SECONDS)
        if resp.status_code != 200:
            raise CultureApiError("http status")
        return resp.text
    except CultureApiError:
        raise
    except Exception:  # 예외 문자열에 URL(serviceKey)이 들어 있을 수 있어 버린다
        raise CultureApiError("request failed") from None


PERIOD_URL = "https://apis.data.go.kr/B553457/cultureinfo/period2"
DETAIL_URL = "https://apis.data.go.kr/B553457/cultureinfo/detail2"
PERIOD_PAGE_SIZE = 1000
PERIOD_MAX_PAGES = 15
SERVICE_TP_SHOW_EXHIBITION = "A"   # period2의 serviceTp=A는 공연+전시. 전시만 normalize_item에서 남긴다


def _call(http_get, url, params):
    try:
        resp = http_get(url, params=params, timeout=TIMEOUT_SECONDS)
        if resp.status_code != 200:
            raise CultureApiError("http status")
        return resp.text
    except CultureApiError:
        raise
    except Exception:  # 예외 문자열에 URL(serviceKey)이 들어 있을 수 있어 버린다
        raise CultureApiError("request failed") from None


def fetch_exhibitions_between(start, end, http_get=None, env=None) -> list:
    """기간 [start, end](date)와 겹치는 전시를 기간 조회 API(period2)로 가져온다. 지난 전시 검색용.
    한 쪽 1000건, 최대 15쪽(1만5천 건)까지. 실패하면 CultureApiError. (목록, 잘렸는지 여부)"""
    import requests
    http_get = http_get or requests.get
    env = os.environ if env is None else env
    key = env.get("CULTURE_API_KEY", "")
    result, seen, truncated = [], set(), False
    for page in range(1, PERIOD_MAX_PAGES + 1):
        raw = _raw_items(_call(http_get, PERIOD_URL, {
            "serviceKey": key, "PageNo": page, "numOfrows": PERIOD_PAGE_SIZE,
            "from": start.strftime("%Y%m%d"), "to": end.strftime("%Y%m%d"),
            "serviceTp": SERVICE_TP_SHOW_EXHIBITION}))
        for e in map(normalize_item, raw):
            if e and e.exhibition_id not in seen:
                seen.add(e.exhibition_id)
                result.append(e)
        if len(raw) < PERIOD_PAGE_SIZE:
            break
    else:
        truncated = True
    return result, truncated


def fetch_detail(exhibition_id, http_get=None, env=None):
    """전시 상세(detail2): 요금·주소·문의·링크·좌표. 실패하거나 항목이 없으면 None(예외를 던지지 않는다)."""
    import requests
    http_get = http_get or requests.get
    env = os.environ if env is None else env
    try:
        raw = _raw_items(_call(http_get, DETAIL_URL, {"serviceKey": env.get("CULTURE_API_KEY", ""),
                                                      "seq": exhibition_id}))
    except Exception:
        return None
    if not raw or not isinstance(raw[0], dict):
        return None
    d = raw[0]

    def num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None
    lat, lon = num(d.get("gpsY")), num(d.get("gpsX"))
    ok_coord = lat is not None and lon is not None and 33 <= lat <= 39 and 124 <= lon <= 132  # 국내 범위만 지도에 표시
    return {"price": _optional_text(d.get("price")), "address": _optional_text(d.get("placeAddr")),
            "phone": _optional_text(d.get("phone")), "url": _optional_text(d.get("url")),
            "place_url": _optional_text(d.get("placeUrl")),
            "lat": lat if ok_coord else None, "lon": lon if ok_coord else None}


def fetch_exhibitions(http_get=None, env=None) -> list:
    """전시 분야 전체를 페이지 단위로 가져온다(요청마다 10초 제한, 재시도 없음, 최대 MAX_PAGES쪽).
    한 쪽이 CULTURE_PAGE_SIZE보다 적게 오면 마지막 쪽으로 본다. 어느 요청이든 실패하면 CultureApiError."""
    import requests
    http_get = http_get or requests.get
    env = os.environ if env is None else env
    key = env.get("CULTURE_API_KEY", "")
    result, seen = [], set()
    for page in range(1, MAX_PAGES + 1):
        raw = _raw_items(_get_page(http_get, key, page))
        for e in map(normalize_item, raw):
            if e and e.exhibition_id not in seen:
                seen.add(e.exhibition_id)
                result.append(e)
        if len(raw) < CULTURE_PAGE_SIZE:
            break
    return result
