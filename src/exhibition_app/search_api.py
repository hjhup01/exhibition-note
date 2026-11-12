"""카카오(다음) 검색 API(웹문서·블로그)로 전시 관련 글을 조회·정리한다. 저장하지 않고 매번 새로 조회한다.

카카오 검색에는 뉴스 검색이 없어 '웹문서'(기사·기관 페이지가 많이 잡힘)와 '블로그' 두 영역을 쓴다.
인증: Authorization: KakaoAK {KAKAO_REST_API_KEY}
"""
import html
import os
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from exhibition_app import messages

TIMEOUT_SECONDS = 10
MAX_ITEMS = 5
REQUEST_SIZE = 10  # 건너뛸 항목이 있어도 5건을 채우도록 넉넉히 받는다(카카오 허용 1~50)
WEB_URL = "https://dapi.kakao.com/v2/search/web"
BLOG_URL = "https://dapi.kakao.com/v2/search/blog"
KINDS = {"web": WEB_URL, "blog": BLOG_URL}
MSG_FAILED = messages.RELATED_FAILED
MSG_EMPTY = messages.NO_RESULT
SEOUL = ZoneInfo("Asia/Seoul")

_TAG_RE = re.compile(r"<[^>]*>")


class RelatedApiError(Exception):
    """카카오 호출 실패·해석 불가 응답. 메시지에 키를 담지 않는다."""


def clean_text(value):
    """HTML 태그를 제거하고 엔티티를 디코딩한다. 문자열이 아니면 ''."""
    if not isinstance(value, str):
        return ""
    return html.unescape(_TAG_RE.sub("", value)).strip()


def to_seoul_date(value):
    """ISO 8601(예: 2026-11-09T10:00:00.000+09:00)을 Asia/Seoul 날짜 YYYY-MM-DD로. 안 되면 None."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        dt = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=SEOUL)
    return dt.astimezone(SEOUL).date().isoformat()


def normalize_related(doc):
    """원본 문서를 {title, link, pub_date, description}로. 건너뛸 항목이면 None."""
    if not isinstance(doc, dict):
        return None
    title = clean_text(doc.get("title"))
    link = doc.get("url")
    link = link.strip() if isinstance(link, str) else ""
    pub_date = to_seoul_date(doc.get("datetime"))
    if not title or not link or not pub_date:
        return None
    return {"title": title, "link": link, "pub_date": pub_date,
            "description": clean_text(doc.get("contents"))}


# 제목에서 이 낱말들만으로는 '같은 전시'라고 볼 수 없다(어느 전시 글에나 나온다)
_GENERIC_WORDS = {"전시", "전시회", "특별전", "기획전", "개인전", "단체전", "초대전", "상설전", "상설", "순회전시",
                  "특별전시", "기획전시", "상설전시", "展", "온라인", "재개관"}
_SEGMENT_SPLIT = re.compile(r"[\[\]()<>《》〈〉「」『』【】_:：,，·|/~\-–—!?'\"“”‘’]+")
_NON_WORD = re.compile(r"[^0-9A-Za-z가-힣一-龥]+")


def _squash(text):
    """비교용: 공백·기호를 빼고 소문자로."""
    return _NON_WORD.sub("", str(text or "")).lower()


def title_keys(title):
    """글이 이 전시에 관한 것인지 볼 때 찾을 핵심어. 제목을 기호로 나눈 구절과 낱말 중 4글자 이상(일반어 제외).
    예: '기록으로 산책하기_서울의 공원' → 기록으로산책하기, 서울의공원, 기록으로, 산책하기.
    4글자 이상이 하나도 없으면(짧은 제목) 제목 전체."""
    keys = []
    for seg in _SEGMENT_SPLIT.split(str(title or "")):
        for cand in [seg] + seg.split():
            k = _squash(cand)
            if len(k) >= 4 and k not in _GENERIC_WORDS and k not in keys:
                keys.append(k)
    if not keys and _squash(title):
        keys.append(_squash(title))
    return keys


def is_relevant(item, title):
    """글 제목·본문에 전시 제목의 핵심어가 하나라도 들어 있으면 관련 글로 본다."""
    text = _squash(f"{item.get('title', '')} {item.get('description', '')}")
    return any(k in text for k in title_keys(title))


def parse_related(payload, title=None):
    """응답 dict에서 정규화·(title이 있으면 관련 글만)·pub_date 내림차순(동률은 응답 순서)·앞 5건.
    해석 불가면 RelatedApiError."""
    docs = payload.get("documents") if isinstance(payload, dict) else None
    if not isinstance(docs, list):
        raise RelatedApiError("documents missing or not an array")
    normalized = [n for n in map(normalize_related, docs) if n]
    if title:  # 검색어와 느슨하게만 맞는 엉뚱한 글(다른 전시 안내·여행 블로그 등)을 뺀다
        normalized = [n for n in normalized if is_relevant(n, title)]
    normalized.sort(key=lambda n: n["pub_date"], reverse=True)  # 안정 정렬
    return normalized[:MAX_ITEMS]


def fetch_related(kind, query, get=None, env=None, title=None):
    """kind('web'|'blog') 검색(10초 제한, 재시도 없음). 실패 시 RelatedApiError."""
    get = get or requests.get
    env = os.environ if env is None else env
    headers = {"Authorization": f"KakaoAK {env.get('KAKAO_REST_API_KEY', '')}"}
    try:
        resp = get(KINDS[kind], params={"query": query, "sort": "accuracy", "size": REQUEST_SIZE},
                   headers=headers, timeout=TIMEOUT_SECONDS)
        if resp.status_code != 200:
            raise RelatedApiError("http error")
        payload = resp.json()
    except RelatedApiError:
        raise
    except Exception as e:  # 타임아웃·네트워크·JSON 오류 모두 실패 처리(예외 문자열은 버린다)
        raise RelatedApiError(type(e).__name__) from None
    return parse_related(payload, title=title)


def load_section(kind, query, get=None, env=None, title=None):
    """한 영역의 표시 상태: {'items': [...], 'message': str|None, 'failed': bool}. 예외를 던지지 않는다."""
    try:
        items = fetch_related(kind, query, get=get, env=env, title=title)
    except Exception:
        return {"items": [], "message": MSG_FAILED, "failed": True}
    return {"items": items, "message": None if items else MSG_EMPTY, "failed": False}


def build_query(title, place=""):
    """검색어 = '전시 제목 장소'. 제목만으로는 일반 낱말(예: 수직정원)이 엉뚱한 글을 끌어와 장소를 붙인다."""
    title = (title or "").replace("_", " ")  # '기록으로 산책하기_서울의 공원'처럼 _로 붙은 낱말을 나눈다
    return " ".join(p.strip() for p in (title, place or "") if p and p.strip())


def load_related(title, place="", get=None, env=None, only_relevant=False):
    """'제목 + 장소'로 웹문서·블로그를 정확도순으로 받아(최신순 재정렬은 parse_related) 매번 새로 조회한다.
    only_relevant=True면 전시 제목의 핵심어가 들어 있는 글만 남긴다(화면·요약용)."""
    query = build_query(title, place)
    keep = title if only_relevant else None
    return {"web": load_section("web", query, get=get, env=env, title=keep),
            "blogs": load_section("blog", query, get=get, env=env, title=keep)}


_MD_SPECIAL = re.compile(r"([\\`*_{}\[\]<>()#+!|~$:])")


def md_escape(text):
    """제목의 마크다운 서식 문자([ ] < > ~ _ * | $ : 등)를 글자 그대로 보이게 이스케이프한다.
    이스케이프하지 않으면 '[해설] 제목'이 링크를 깨거나 '~'·'_'가 취소선·기울임으로 바뀌어 글씨 모양이 달라진다."""
    return _MD_SPECIAL.sub(r"\\\1", text)


def md_link_target(url):
    """링크 주소의 공백·괄호를 인코딩해 마크다운 링크가 끊기지 않게 한다."""
    return url.replace(" ", "%20").replace("(", "%28").replace(")", "%29")


def render_section(st, heading, section):
    """영역 하나를 Streamlit에 그린다. 본문 요약(description)은 표시하지 않는다."""
    st.subheader(heading)
    if section["message"]:
        st.write(section["message"])
        return
    for it in section["items"]:
        st.markdown(f"[{md_escape(it['title'])}]({md_link_target(it['link'])}) · {it['pub_date']}")


def render_related(st, related):
    render_section(st, messages.WEB_HEADING, related["web"])
    render_section(st, messages.BLOG_HEADING, related["blogs"])
