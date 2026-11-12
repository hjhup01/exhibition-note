"""RAG 파이프라인: 전시 정보·관련 글 문서(data/corpus.jsonl)를 검색한다.

검색 단계
1. 쿼리 확장(expand_query): 지역 별칭(서울시→서울), 장소 동의어(미술관↔갤러리), 후기 동의어(후기↔리뷰·관람기)
2. 1차 검색(BM25): 한글은 글자 2-gram, 영문·숫자는 단어 단위로 색인한다(형태소 분석기 없이 동작).
3. 재정렬(rerank): 제목 일치 가산, 지역 필터 일치 가산, 진행 중 전시 가산, 종료된 전시 감점.
결과는 API의 contexts 형식({doc_id, text, ...})으로 돌려준다. 외부 패키지가 필요 없다.
"""
import json
import math
import os
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORPUS_PATH = ROOT / "data" / "corpus.jsonl"

BM25_K1 = 1.5
BM25_B = 0.75

REGION_ALIASES = {
    "서울": ["서울시", "서울특별시"], "부산": ["부산시", "부산광역시"], "대구": ["대구광역시"],
    "인천": ["인천광역시"], "광주": ["광주광역시"], "대전": ["대전광역시"], "울산": ["울산광역시"],
    "경기": ["경기도"], "강원": ["강원도"], "충북": ["충청북도"], "충남": ["충청남도"], "전북": ["전라북도"],
    "전남": ["전라남도"], "경북": ["경상북도"], "경남": ["경상남도"], "제주": ["제주도"], "세종": ["세종시"],
}
SYNONYMS = {
    "미술관": ["갤러리", "아트센터"], "갤러리": ["미술관"], "후기": ["리뷰", "관람기", "다녀온"],
    "리뷰": ["후기"], "전시": ["전시회", "展"], "전시회": ["전시"], "추천": ["가볼만한", "볼만한"],
}


def tokenize(text):
    """한글은 2-gram(1글자 단어는 그대로), 영문·숫자는 소문자 단어."""
    text = (text or "").lower()
    tokens = []
    for word in re.findall(r"[가-힣]+|[a-z0-9]+", text):
        if re.match(r"[가-힣]", word):
            tokens.extend([word] if len(word) == 1 else [word[i:i + 2] for i in range(len(word) - 1)])
        else:
            tokens.append(word)
    return tokens


def expand_query(query):
    """쿼리 확장: 별칭·동의어를 덧붙인 문자열과, 쿼리에서 찾은 지역(없으면 None)."""
    q = query or ""
    extra, region = [], None
    for short, longs in REGION_ALIASES.items():
        if short in q or any(l in q for l in longs):
            region = region or short
            extra.append(short)
    for word, syns in SYNONYMS.items():
        if word in q:
            extra.extend(syns)
    return (q + " " + " ".join(extra)).strip(), region


@dataclass
class Doc:
    doc_id: str
    text: str
    meta: dict = field(default_factory=dict)


def load_corpus(path=None):
    path = Path(path or os.environ.get("CORPUS_PATH") or CORPUS_PATH)
    if not path.exists():
        return []
    docs = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                d = json.loads(line)
                docs.append(Doc(d["doc_id"], d["text"], {k: v for k, v in d.items() if k not in ("doc_id", "text")}))
    return docs


class Retriever:
    def __init__(self, docs):
        self.docs = list(docs)
        self._tf = [Counter(tokenize(d.text)) for d in self.docs]
        self._len = [sum(tf.values()) for tf in self._tf]
        self._avg = (sum(self._len) / len(self._len)) if self._len else 1.0
        df = Counter()
        for tf in self._tf:
            df.update(tf.keys())
        n = len(self.docs)
        self._idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}

    def _bm25(self, i, q_tokens):
        tf, dl, s = self._tf[i], self._len[i], 0.0
        for t in q_tokens:
            f = tf.get(t)
            if f:
                s += self._idf[t] * f * (BM25_K1 + 1) / (f + BM25_K1 * (1 - BM25_B + BM25_B * dl / self._avg))
        return s

    def search(self, query, k=5, doc_type=None, exhibition_id=None, today=None, candidates=30):
        """query로 문서를 찾아 상위 k개. doc_type('exhibition'|'post')·exhibition_id로 거를 수 있다."""
        expanded, region = expand_query(query)
        q_tokens = tokenize(expanded)
        if not q_tokens or not self.docs:
            return []
        today = (today or date.today()).isoformat()
        scored = []
        for i, d in enumerate(self.docs):
            if doc_type and d.meta.get("type") != doc_type:
                continue
            if exhibition_id and d.meta.get("exhibition_id") != str(exhibition_id):
                continue
            s = self._bm25(i, q_tokens)
            if s > 0:
                scored.append((s, i))
        scored.sort(reverse=True)
        reranked = []
        for s, i in scored[:candidates]:
            m = self.docs[i].meta
            bonus = 1.0
            title = (m.get("title") or "").lower()
            if title and title[:6] in (query or "").lower():
                bonus += 0.5                      # 제목을 직접 언급
            if region and m.get("region") == region:
                bonus += 0.3                      # 지역 일치
            start, end = m.get("start_date"), m.get("end_date")
            if start and end:
                if end < today:
                    bonus -= 0.5                  # 이미 끝난 전시
                elif start <= today:
                    bonus += 0.2                  # 진행 중
            reranked.append((s * bonus, i))
        reranked.sort(reverse=True)
        return [self._as_context(i, score) for score, i in reranked[:k]]

    def _as_context(self, i, score):
        d = self.docs[i]
        return {"doc_id": d.doc_id, "text": d.text, "score": round(score, 3), **d.meta}


_DEFAULT = None


def get_retriever():
    """data/corpus.jsonl을 한 번만 읽어 재사용한다."""
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = Retriever(load_corpus())
    return _DEFAULT
