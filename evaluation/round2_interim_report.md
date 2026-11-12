# 2차 자체 평가 — 중간 실행 (참고용)

> 1차 개선(근거 contexts 누락 수정, `place` 조건, RAG 우선 규칙) 직후의 중간 실행 기록이다. 남은 3번 실패(문장부호 때문에 제목 키워드가 일치하지 않음)를 고친 뒤 다시 실행한 최종 결과는 [round2_report.md](round2_report.md)에 있다.

- 실행: 2026-11-12 09:05 (Asia/Seoul) · 모델: `global.anthropic.claude-haiku-4-5-20251001-v1:0`
- 세트: `evaluation/test_queries.csv` 18건 · 판정: 도구 호출 검사 + LLM-as-Judge(같은 모델, 항목별 판정)
- 평가용 본인 기록: 관심 2 · 관람예정 1 · 관람완료 2 (별점 [5, 3])

## 통과율: **17 / 18** (94%)

| 분류 | 통과 | 전체 |
|---|---|---|
| positive | 6 | 7 |
| negative | 4 | 4 |
| edge | 4 | 4 |
| guardrail | 3 | 3 |

## 케이스별 결과

| id | 분류 | 결과 | 호출 도구 | 실패 사유 |
|---|---|---|---|---|
| 1 | positive | ✅ | search_exhibitions | - |
| 2 | positive | ✅ | search_exhibitions | - |
| 3 | positive | ❌ | search_exhibitions | 도구 미호출: retrieve_docs<br>미충족: 전시 장소(부산현대미술관) 언급 — 답변에서 전시 장소를 언급하지 않았습니다. 에이전트는 현재 진행 중인 전시를 찾을 수 없다고만 응답했습니다.<br>미충족: 관람 후기·특징 요약 — 전시를 찾을 수 없다고 응답했으므로 관람 후기나 특징을 요약하지 않았습니다.<br>미충족: 출처(웹문서 또는 블로그) 언급 — 답변에서 출처를 언급하지 않았습니다. |
| 4 | positive | ✅ | search_exhibitions | - |
| 5 | positive | ✅ | search_exhibitions | - |
| 6 | positive | ✅ | get_my_records | - |
| 7 | positive | ✅ | get_my_records | - |
| 8 | negative | ✅ | - | - |
| 9 | negative | ✅ | search_exhibitions | - |
| 10 | negative | ✅ | - | - |
| 11 | negative | ✅ | - | - |
| 12 | edge | ✅ | search_exhibitions | - |
| 13 | edge | ✅ | search_exhibitions | - |
| 14 | edge | ✅ | search_exhibitions, retrieve_docs | - |
| 15 | edge | ✅ | search_exhibitions | - |
| 16 | guardrail | ✅ | - | - |
| 17 | guardrail | ✅ | - | - |
| 18 | guardrail | ✅ | - | - |

## 답변 원문 (실패 케이스)

### 3. 패트릭 블랑 수직정원 전시 후기 요약해 줘

```
현재 진행 중인 "패트릭 블랑 수직정원" 전시를 찾을 수 없습니다.

혹시 다음 중 하나에 해당하나요?
- **과거에 종료된 전시**인 경우
- **다른 제목**으로 진행 중인 경우
- **특정 지역**의 전시를 찾고 계신 경우

전시 제목, 개최 지역, 또는 대략적인 기간을 알려주시면 더 정확하게 찾아드릴 수 있습니다.
```
