# 2차 자체 평가 결과

- 실행: 2026-11-12 09:14 (Asia/Seoul) · 모델: `global.anthropic.claude-haiku-4-5-20251001-v1:0`
- 세트: `evaluation/test_queries.csv` 18건 · 판정: 도구 호출 검사 + LLM-as-Judge(같은 모델, 항목별 판정)
- 평가용 본인 기록: 관심 2 · 관람예정 1 · 관람완료 2 (별점 [5, 3])

## 통과율: **18 / 18** (100%)

| 분류 | 통과 | 전체 |
|---|---|---|
| positive | 7 | 7 |
| negative | 4 | 4 |
| edge | 4 | 4 |
| guardrail | 3 | 3 |

## 케이스별 결과

| id | 분류 | 결과 | 호출 도구 | 실패 사유 |
|---|---|---|---|---|
| 1 | positive | ✅ | search_exhibitions | - |
| 2 | positive | ✅ | search_exhibitions | - |
| 3 | positive | ✅ | search_exhibitions, retrieve_docs | - |
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

## RAGAS 지표

- 대상: 근거 문서가 있는 10건 (id 1, 2, 3, 4, 5, 6, 7, 12, 14, 15) · 심판 `global.anthropic.claude-haiku-4-5-20251001-v1:0` · 임베딩 `amazon.titan-embed-text-v2:0`

| 지표 | 평균 |
|---|---|
| context_recall | 0.58 |
| context_precision | 0.49 |
| faithfulness | 0.88 |
| answer_relevancy | 0.45 |

| id | context_recall | context_precision | faithfulness | answer_relevancy |
|---|---|---|---|---|
| 1 | 0.00 | 0.00 | 0.75 | 0.54 |
| 2 | 0.00 | 0.81 | 0.80 | 0.51 |
| 3 | 0.33 | 0.00 | 1.00 | 0.37 |
| 4 | 0.00 | 0.88 | 0.94 | 0.49 |
| 5 | 1.00 | 0.77 | 1.00 | 0.43 |
| 6 | 1.00 | 0.00 | 0.83 | 0.60 |
| 7 | 1.00 | 1.00 | 1.00 | 0.51 |
| 12 | 1.00 | 0.49 | 0.90 | 0.50 |
| 14 | 0.50 | 0.00 | 1.00 | 0.35 |
| 15 | 1.00 | 1.00 | 0.56 | 0.14 |
