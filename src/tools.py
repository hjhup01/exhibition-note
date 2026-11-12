"""에이전트가 고르는 도메인 도구 4종. 기존 기능(exhibition_app)을 LangChain 도구로 감싼다.

- search_exhibitions   : 공공데이터 전시 목록 실시간 조회 + 기간·지역·키워드·미술관 필터 (실패하면 코퍼스로 대체)
- retrieve_docs        : RAG — 전시 정보·관련 글 코퍼스 검색 (retriever.py)
- search_related_posts : 카카오 웹문서·블로그 실시간 검색 (최신 후기)
- get_my_records       : 내 관람 기록(관심·관람예정·관람완료·별점·관람평) 조회

모든 도구는 예외를 던지지 않고 {"ok": bool, ..., "contexts": [{doc_id, text}]} 형태를 돌려준다.
contexts는 API 응답의 근거(contexts)로 그대로 쓰인다.
"""
import json
import time

from langchain_core.tools import tool

from exhibition_app import config, culture_api, filters, messages, repository, search_api
from retriever import get_retriever

_CACHE = {"at": 0.0, "items": None}
CACHE_SECONDS = 600
PERIODS = {"진행중": messages.PERIOD_ONGOING, "진행예정": messages.PERIOD_UPCOMING, "전체": messages.PERIOD_ALL}


def _exhibitions():
    """공공데이터 전시 목록(10분 캐시). 실패하면 코퍼스의 전시 문서로 대체한다. (목록, 출처)"""
    if _CACHE["items"] is not None and time.time() - _CACHE["at"] < CACHE_SECONDS:
        return _CACHE["items"], "공공데이터 API"
    try:
        items = culture_api.fetch_exhibitions()
        _CACHE.update(at=time.time(), items=items)
        return items, "공공데이터 API"
    except Exception:
        docs = [d for d in get_retriever().docs if d.meta.get("type") == "exhibition"]
        items = [culture_api.Exhibition(d.meta["exhibition_id"], d.meta["title"], "전시", d.meta.get("region", ""),
                                        d.meta.get("place", ""), d.meta["start_date"], d.meta["end_date"])
                 for d in docs]
        return items, "저장된 코퍼스(공공데이터 API 응답 실패)"


def _exhibition_context(e):
    return {"doc_id": f"ex-{e.exhibition_id}",
            "text": f"[전시] {e.title} / 장소: {e.place or '정보 없음'} ({e.region or '지역 정보 없음'}) / 기간: {e.start_date} ~ {e.end_date}"}


@tool
def search_exhibitions(region: str = "", period: str = "진행중", keyword: str = "", place: str = "",
                       art_only: bool = False, limit: int = 8) -> dict:
    """국내 전시 목록을 조회한다(공공데이터). 전시를 추천·검색하거나 기간·지역을 확인할 때 쓴다.

    Args:
        region: 시·도 짧은 이름(예: 서울, 부산, 경기). 비우면 전국.
        period: '진행중' | '진행예정' | '전체'.
        keyword: 전시 '제목'에 들어갈 낱말(예: 모네, 사진). 비우면 조건 없음.
        place: 전시 '장소·기관' 이름에 들어갈 낱말(예: 국립현대미술관, 리움). 기관을 묻는 질문은 keyword가 아니라 place로 찾는다.
        art_only: True면 장소가 미술관·갤러리인 전시만.
        limit: 최대 개수(1~20, 기본 8).
    """
    items, source = _exhibitions()
    today = config.today_kst()
    region = culture_api.normalize_region(region) if region else messages.REGION_ALL
    shown = filters.filter_exhibitions(filters.base_set(items, today), today,
                                       PERIODS.get(period, messages.PERIOD_ONGOING),
                                       region or messages.REGION_ALL, keyword, art_only=bool(art_only))
    want_place = (place or "").replace(" ", "").casefold()
    if want_place:
        shown = [e for e in shown if want_place in (e.place or "").replace(" ", "").casefold()]
    shown = shown[:max(1, min(int(limit or 8), 20))]
    return {"ok": True, "source": source, "today": today.isoformat(), "count": len(shown),
            "exhibitions": [{"exhibition_id": e.exhibition_id, "title": e.title, "place": e.place,
                             "region": e.region, "start_date": e.start_date, "end_date": e.end_date}
                            for e in shown],
            "contexts": [_exhibition_context(e) for e in shown]}


@tool
def retrieve_docs(query: str, exhibition_id: str = "", k: int = 5) -> dict:
    """전시 정보와 전시 관련 글(웹문서·블로그 요약) 코퍼스를 검색한다(RAG). 특정 전시의 분위기·후기·특징·장소 정보를 근거와 함께 답할 때 쓴다.

    Args:
        query: 찾을 내용(예: '패트릭 블랑 수직정원 후기', '서울 사진전 추천').
        exhibition_id: 특정 전시로 한정할 때 그 전시 ID(search_exhibitions 결과의 exhibition_id).
        k: 가져올 문서 수(1~8).
    """
    hits = get_retriever().search(query, k=max(1, min(int(k or 5), 8)), exhibition_id=exhibition_id or None,
                                  today=config.today_kst())
    return {"ok": True, "count": len(hits),
            "documents": [{"doc_id": h["doc_id"], "type": h.get("type"), "title": h.get("title"),
                           "url": h.get("url"), "score": h["score"]} for h in hits],
            "contexts": [{"doc_id": h["doc_id"], "text": h["text"]} for h in hits]}


@tool
def search_related_posts(title: str, place: str = "") -> dict:
    """카카오 검색으로 특정 전시의 최신 웹문서·블로그 글을 실시간 조회한다. retrieve_docs로 먼저 찾은 뒤 근거가 없거나 부족할 때만 쓴다.

    Args:
        title: 전시 제목.
        place: 전시 장소(정확도를 높인다).
    """
    rel = search_api.load_related(title, place=place)
    contexts, out = [], {}
    for key, label in (("web", "웹문서"), ("blogs", "블로그")):
        sec = rel[key]
        out[key] = {"message": sec["message"], "items": [
            {"title": i["title"], "url": i["link"], "pub_date": i["pub_date"]} for i in sec["items"]]}
        for n, i in enumerate(sec["items"]):
            contexts.append({"doc_id": f"live-{key}-{n}",
                             "text": f"[{label}] {i['title']}\n{i['description']}\n출처: {i['link']} ({i['pub_date']})"})
    return {"ok": any(rel[k]["items"] for k in ("web", "blogs")), **out, "contexts": contexts}


@tool
def get_my_records(status: str = "전체") -> dict:
    """이 사용자 본인의 관람 기록(관심·관람예정·관람완료, 관람예정일·실제 관람일, 별점·관람평)을 조회한다.

    Args:
        status: '전체' | '관심' | '관람예정' | '관람완료'.
    """
    db = config.db_path()
    if not repository.init_db(db).ok:
        return {"ok": False, "message": messages.STORE_UNAVAILABLE, "records": [], "contexts": []}
    rows = repository.list_all(db) if status in ("", "전체") else repository.list_by_status(db, status)
    keep = ("exhibition_id", "title", "place", "region", "status", "planned_visit_date", "actual_visit_date",
            "review_rating", "review_text")
    records = [{k: r.get(k) for k in keep} for r in rows]
    contexts = [{"doc_id": f"rec-{r['exhibition_id']}",
                 "text": "[내 기록] " + json.dumps({k: v for k, v in r.items() if v is not None}, ensure_ascii=False)}
                for r in records]
    return {"ok": True, "count": len(records), "records": records, "contexts": contexts}


TOOLS = [search_exhibitions, retrieve_docs, search_related_posts, get_my_records]
