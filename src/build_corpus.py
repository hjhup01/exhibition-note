"""RAG용 문서 만들기: 공공데이터 전시 목록 + 전시별 카카오 웹문서·블로그 글 → data/corpus.jsonl.

실행: python src/build_corpus.py [--max-exhibitions 60]
- 전시 문서(type=exhibition): 아직 끝나지 않은 '전시' 분야 전체
- 글 문서(type=post): 미술관·갤러리 전시 중 앞쪽 N개에 대해 웹문서·블로그 각 5건(제목·본문 요약·링크·날짜)
키는 .env에서 읽고, 파일에는 키를 쓰지 않는다.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent))
from exhibition_app import config, culture_api, filters, search_api  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def exhibition_doc(e):
    text = (f"[전시] {e.title}\n장소: {e.place or '정보 없음'} ({e.region or '지역 정보 없음'})\n"
            f"기간: {e.start_date} ~ {e.end_date}\n분야: {e.category}")
    return {"doc_id": f"ex-{e.exhibition_id}", "type": "exhibition", "text": text,
            "exhibition_id": e.exhibition_id, "title": e.title, "place": e.place, "region": e.region,
            "start_date": e.start_date, "end_date": e.end_date,
            "art_venue": filters.is_art_venue(e.place)}


def post_docs(e, related):
    docs = []
    for kind, key in (("웹문서", "web"), ("블로그", "blogs")):
        for it in related[key]["items"]:
            h = hashlib.sha1(it["link"].encode()).hexdigest()[:10]
            docs.append({"doc_id": f"post-{e.exhibition_id}-{h}", "type": "post",
                         "text": f"[{kind}] {it['title']}\n{it['description']}\n출처: {it['link']} ({it['pub_date']})",
                         "exhibition_id": e.exhibition_id, "title": e.title, "region": e.region,
                         "place": e.place, "source": kind, "url": it["link"], "pub_date": it["pub_date"]})
    return docs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-exhibitions", type=int, default=60)
    args = ap.parse_args()
    load_dotenv(ROOT / ".env")
    today = config.today_kst()
    exhibitions = filters.base_set(culture_api.fetch_exhibitions(), today)
    docs = [exhibition_doc(e) for e in exhibitions]
    art = [e for e in exhibitions if filters.is_art_venue(e.place) and e.start_date <= today.isoformat()]
    seen = set()
    for n, e in enumerate(art[:args.max_exhibitions], 1):
        for d in post_docs(e, search_api.load_related(e.title, place=e.place)):
            if d["doc_id"] not in seen:
                seen.add(d["doc_id"])
                docs.append(d)
        print(f"\r관련 글 수집 {n}/{min(len(art), args.max_exhibitions)}", end="", flush=True)
    out = ROOT / "data" / "corpus.jsonl"
    out.parent.mkdir(exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        for d in docs:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    meta = {"built_at": today.isoformat(), "exhibitions": len(exhibitions),
            "posts": sum(1 for d in docs if d["type"] == "post"), "post_exhibitions": min(len(art), args.max_exhibitions)}
    (ROOT / "data" / "corpus_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n", meta)


if __name__ == "__main__":
    main()
