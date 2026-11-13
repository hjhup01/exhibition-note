# 미니 PJT: 전시노트 — 미술 전시 도우미 에이전트

**배포 주소:** https://exhibition-note-hjhup01.streamlit.app

## 이용 범위: 구글 로그인이 필요한 기능
| 기능 | 로그인 없이 | 구글 로그인 후 |
|---|:---:|:---:|
| 전시 찾기: 필터(기간·지역·구·키워드·미술관만)·정렬·지난 전시 | ✅ | ✅ |
| 전시 상세: 포스터·요금·주소·문의·지도·카카오맵 길찾기·관련 글·AI 요약 | ✅ | ✅ |
| AI 도우미: 전시 추천·후기 요약 질문 | ✅ | ✅ |
| **관심 저장** (상세 칸의 ⭐ 관심 저장) | — | ✅ |
| **내 전시**: 관심 → 관람예정 → 관람완료, 관람예정일·실제 관람일 | — | ✅ |
| **관람평**(별점·글)·**관람 사진**(3장) 등록·수정·삭제 | — | ✅ |

> **현재 구글 로그인은 테스트 단계다.** 관리자가 구글 클라우드 콘솔에서 **테스터로 등록한 일부 구글 계정만** 로그인할 수 있고, 등록되지 않은 계정은 구글 로그인 화면에서 차단된다. 위 표에서 '로그인 없이' 칸이 ✅인 기능은 계정과 관계없이 쓸 수 있다.
>
> 로그인한 사람의 기록은 **그 사람의 구글 드라이브**('전시노트 기록' 시트, '전시노트 사진' 폴더)에만 저장되며, 앱은 '앱이 만든 파일만' 접근하는 권한(`drive.file`)만 쓴다. 다른 사람의 기록은 보이지 않는다.
>
> AI 도우미의 '내 기록' 질문(예: "내가 관람완료한 전시 알려줘")은 지금은 **로컬 실행(이 PC의 SQLite)** 기록을 읽는다. 배포 앱에서는 로그인한 사람의 구글 시트와 아직 연결되어 있지 않다.

## 무엇을 푸나
갈 만한 국내 미술 전시를 고르고 다녀온 기록을 남기기까지 포털·블로그·메모 앱을 오가야 하는 번거로움을, 질문 한 줄로 근거 있는 추천·후기 요약·내 관람 기록 조회까지 해 주는 에이전트로 해결한다. (자세한 기획: [SERVICE.md](SERVICE.md))

## 활용한 패턴 (Day 1~7)
- **Day 1: LCEL chain + Pydantic 구조화 출력** — `compose` 노드에서 `prompt | llm.with_structured_output(FinalAnswer)`로 최종 답변과 인용 문서 ID(`used_doc_ids`)를 구조화해 받는다. (`src/agent.py` `FinalAnswer`, `COMPOSE_PROMPT`)
- **Day 2: RAG (쿼리 확장·재정렬)** — 공공데이터 전시 319건 + 카카오 웹문서·블로그 588건 코퍼스를 BM25(한글 2-gram)로 검색하고, 지역 별칭·동의어로 쿼리를 확장, 제목 일치·지역·진행 여부로 재정렬한다. (`src/retriever.py`)
- **Day 3: ReAct (도구 자율 선택)** — `create_react_agent`(bind_tools)로 질문에 맞는 도구를 스스로 고른다. (`src/agent.py` `react` 노드)
- **Day 4: 도구 다중 (외부 API·DB)** — 공공데이터 API, 카카오 검색 API, RAG, 내 기록 DB 도구 4종을 한 질의에서 결합한다(예: 기간 확인 + 후기 검색). (`src/tools.py`)
- **Day 5: 가드레일** — 입력 단계에서 프롬프트 인젝션·비밀값·타인 정보 요청 차단, 출력 단계에서 비밀값·시스템 프롬프트 유출 차단. (`src/guardrails.py`)
- **Day 5: 미들웨어 (PII 마스킹·재시도)** — 질문 속 전화번호·이메일·주민번호를 LLM 호출 전에 마스킹, 외부 API 실패 시 코퍼스 대체·안내 문구로 계속 동작, Bedrock 재시도 1회.
- **Day 7: Observability · Trace** — LangSmith로 그래프 전체(가드레일·도구 호출·LLM)를 추적하고, API 응답 `trace`에도 단계별 입출력을 담는다.
- **Day 7: 평가 (RAGAS · LLM-as-Judge)** — 인-아웃 세트 18건을 도구 호출 검사 + LLM-as-Judge로 1·2차 채점하고, RAGAS 4개 지표를 계산한다. (`evaluation/`)

## 아키텍처
화면 기능: 위쪽 메뉴(전시 찾기·내 전시·AI 도우미) · 로고를 누르면 처음 화면 · 필터 카드(기간(전체/전시중/전시예정/지난 전시+기간 지정)·정렬·지역 여러 개 + 서울 구 단위·키워드·미술관·갤러리만) · 전시 상세(포스터·요금·주소·문의·지도(카카오맵 보기·길찾기)·관련 글·AI 요약) · 내 전시(관심→관람예정→관람완료, 실제 관람일, 별점·관람평, 관람 사진 3장(내 구글 드라이브 '전시노트 사진' 폴더)) · AI 도우미(에이전트 대화).

```
사용자 ─┬─ Streamlit 화면 (src/app.py): 전시 찾기 · 내 전시 · AI 도우미
        └─ POST /query (src/api.py, FastAPI)
                 │
                 ▼
   ┌──────────── LangGraph (src/agent.py) ────────────┐
   │ input_guard ─(차단)→ 거절 답변                    │
   │      │ (통과, PII 마스킹)                         │
   │      ▼                                            │
   │ react: ReAct 에이전트 ──┬─ search_exhibitions ──→ 공공데이터 API
   │  (Claude Haiku 4.5,     ├─ retrieve_docs ───────→ RAG (data/corpus.jsonl)
   │   bind_tools)           ├─ search_related_posts → 카카오 검색 API
   │      │                  └─ get_my_records ──────→ SQLite / 구글 시트
   │      ▼                                            │
   │ compose: LCEL → FinalAnswer(Pydantic)             │
   │      ▼                                            │
   │ output_guard → {answer, contexts, trace}          │
   └───────────────────────────────────────────────────┘
          모든 단계 LangSmith 트레이스
```

## 실행 방법
```bash
# 0) 준비: Python 3.12, 키 설정
cp .env.example .env        # CULTURE_API_KEY, KAKAO_REST_API_KEY, AWS_*, BEDROCK_MODEL_ID, LANGSMITH_* 입력
pip install -r requirements.txt

# 1) API (표준 규약: POST /query)
./run.sh api                # = uvicorn api:app --app-dir src --port 8000
curl -X POST localhost:8000/query -H "Content-Type: application/json" \
     -d '{"question": "이번 주 서울에서 볼 만한 미술관 전시 추천해 줘"}'

# 2) 화면 (Streamlit)
./run.sh app                # = streamlit run src/app.py  → http://localhost:8501
# Streamlit Cloud 배포: Main file path = app.py (맨 위 app.py가 src/app.py를 실행한다)

# 3) 평가
./run.sh eval 1             # 인-아웃 세트 자체 평가 → evaluation/round1_report.md
uv run --no-project --python 3.12 --with "ragas==0.4.3" --with "langchain-community<0.4" \
    --with "langchain-aws<1" --with python-dotenv python evaluation/ragas_eval.py --round 1

# 4) 테스트 / 코퍼스 재생성 / Docker
./run.sh test               # 단위·화면 테스트 (키 없이 실행)
./run.sh corpus             # data/corpus.jsonl 다시 만들기
docker build -t exhibition-note . && docker run --rm -p 8000:8000 --env-file .env exhibition-note
```

## RAGAS 평가 결과
2차(최종) 기준. 근거 문서가 있는 12건(id 1~7, 9, 12~15) 대상, 심판 Bedrock Claude Haiku 4.5 · 임베딩 Titan Text Embeddings v2 (`evaluation/ragas_eval.py`).

| 지표 | 1차 | **2차 (최종)** |
|---|---|---|
| context_recall | 0.55 | **0.58** |
| context_precision | 0.48 | **0.49** |
| faithfulness | 0.79 | **0.88** |
| answer_relevancy | 0.47 | **0.45** |

- context_recall: 0.58
- context_precision: 0.49
- faithfulness: 0.88
- answer_relevancy: 0.45

해석: 근거 충실도(faithfulness)는 목표 0.80을 넘었다. answer_relevancy가 낮은 이유는 답변이 '목록 + 안내 한 줄' 형식이라 RAGAS가 답변에서 역으로 만든 질문과 원 질문의 임베딩 유사도가 낮게 나오기 때문으로 본다(한국어 질문을 Titan 임베딩으로 비교). context_recall·precision은 실시간 데이터라 기준 답변(reference)을 개별 전시명 대신 '답이 담아야 할 사실'로 적은 영향이 크다. 케이스별 수치는 `evaluation/round1_report.md`, `round2_report.md` 하단.

## 인-아웃 세트 통과율 (자체 평가)
세트: `evaluation/test_queries.csv` 18건 (positive 7 · negative 4 · edge 4 · guardrail 3). 판정 = 기대 도구 호출 + LLM-as-Judge 항목별 판정(expected_traits 모두 충족 · forbidden 없음).

- 1차 (Day 9 종료): **14 / 18** 통과 (78%) — guardrail 3/3, negative 4/4, positive 4/7, edge 3/4
- 2차 (Day 10 개선 후): **18 / 18** 통과 (100%) — 전 분류 통과
- 회귀 확인 (화면 기능 추가 후, 최종 코드): **18 / 18** — [round3_report.md](evaluation/round3_report.md)
- 개선폭: **+4 건** (주요 개선 사항: 답변이 언급한 전시의 근거가 contexts에서 잘리던 문제 수정 · `search_exhibitions`에 장소(`place`) 조건 추가 · 후기 질문은 RAG(`retrieve_docs`) 우선 · 문장부호가 섞인 제목 키워드 일치 · 기간 표기를 근거 문서 그대로 쓰도록 지시)
- 공정성: 2차 도중 심판(LLM-as-Judge)이 항목에 없는 조건(URL)을 요구하거나 근거와 결론이 어긋나는 문제를 발견해 심판 프롬프트를 고쳤다. **1차 답변도 같은 새 심판으로 다시 채점**했고 결과는 그대로 14/18이었다. 중간 실행 기록은 `evaluation/round2_interim_report.md`.
- 보고서: [round1_report.md](evaluation/round1_report.md) · [round2_report.md](evaluation/round2_report.md)

## 트라이앤에러 회고
**시도했지만 실패한 접근 · 왜 실패했는가**
- *전시 목록을 LLM이 직접 만들게 하기* — 최신 전시를 모르거나 지어낸다. 목록은 공공데이터 도구 결과만 쓰고, LLM은 고르고 요약하는 역할로 제한했다.
- *분야 '미술'로 거르기* — 실제 공공데이터 응답에는 '미술' 분류가 없고 전부 '전시'였다(실호출로 확인). 장소 이름(미술관·갤러리)으로 거르는 `art_only` 조건으로 바꿨다.
- *네이버 검색* → *카카오 검색* — 사용 정책상 카카오로 바꿨는데 카카오에는 뉴스 검색이 없어 '웹문서 + 블로그'로 구성했다. 제목만으로 검색하면 일반 낱말(예: 수직정원)이 엉뚱한 글을 끌어와 '제목 + 장소', 정확도순으로 바꿨다.
- *RAGAS 최신판을 에이전트와 같은 환경에서 실행* — ragas 0.4.3이 LangChain 1.x와 충돌했다. 에이전트 실행 결과를 JSON으로 저장하고, RAGAS는 호환 버전 조합의 별도 환경에서 채점하도록 분리했다.
- *Bedrock Sonnet 모델* — 계정의 하루 토큰 한도에 바로 걸렸다. 요약·도구 선택에는 Haiku 4.5로 충분해 바꿨다(비용도 낮음).
- *심판 프롬프트 1판* — 항목에 없는 조건(URL)을 요구하고, 근거('아직 진행 중')와 결론('위반')이 어긋났다. 근거를 먼저 쓰고 결론을 맞추게 하고 항목을 글자 그대로 해석하게 고친 뒤, 1·2차를 같은 심판으로 다시 채점했다.

**최종 채택한 접근 · 왜 그것으로 갔는가**
- LangGraph로 **가드레일 → ReAct → LCEL 구조화 답변 → 가드레일**을 명시적 노드로 나눴다. 위험한 질문은 LLM 호출 전에 끊고(비용·유출 방지), 최종 답변은 근거 문서만 보고 다시 써서 지어내기를 줄였다(faithfulness 0.79 → 0.88).
- RAG는 형태소 분석기 없이 한글 2-gram BM25 + 쿼리 확장 + 재정렬로 만들었다. 배포 환경(Streamlit Cloud)에 무거운 의존성을 넣지 않기 위해서다.
- 기존 앱 기능(공공데이터 조회·카카오 검색·기록 규칙)을 그대로 도구로 감싸, 화면과 에이전트가 같은 규칙을 공유한다.

**남은 한계 · 향후 개선 방향**
- answer_relevancy(0.45)가 낮다. 목록형 답변의 형식을 질문 유형별로 다듬고, 한국어 임베딩 모델로 재측정해 볼 필요가 있다.
- 평가 세트가 18건이라 작고, 심판이 같은 모델(Haiku)이다. 다른 모델 심판·사람 검수를 섞어 편향을 줄이고 세트를 늘릴 계획이다.
- 코퍼스는 2026-11-12 스냅샷이다. 매일 `./run.sh corpus`로 갱신하는 스케줄이 필요하다.
- 에이전트가 기록을 쓰는 동작(관심 저장 등)은 아직 화면에서만 한다. HITL(사용자 승인 후 저장)로 에이전트에 붙이는 것이 다음 단계다.

## 핵심 코드 위치
- `src/agent.py:111` — 메인 에이전트 그래프 (`build_graph`: input_guard → react → compose → output_guard)
- `src/agent.py:207` — `run`: 질의 1건 처리 → API 응답 형식 `{answer, contexts, trace}`
- `src/tools.py` — 도메인 도구 4종 (목록 `src/tools.py:135`) (`search_exhibitions`, `retrieve_docs`, `search_related_posts`, `get_my_records`)
- `src/retriever.py` — RAG 파이프라인 (토크나이저, 쿼리 확장, BM25, 재정렬 · 검색 `src/retriever.py:102`)
- `src/guardrails.py` — 입력·출력 가드레일, PII 마스킹
- `src/api.py` — `POST /query` (FastAPI)
- `src/app.py` — Streamlit 화면 (전시 찾기 · 내 전시 · AI 도우미)
- `src/exhibition_app/` — 공공데이터·카카오 연동, 기록 저장 규칙(SQLite/구글 시트)
- `evaluation/` — `test_queries.csv`, `run_eval.py`, `ragas_eval.py`, `round1_report.md`, `round2_report.md`
- `tests/` — 단위·화면 테스트
