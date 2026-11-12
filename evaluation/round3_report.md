# 3차 자체 평가 — 화면 기능 추가 후 회귀 확인

> 2차 이후 화면 기능(처음 화면 버튼, 지난 전시 기간 검색, 전시중·전시예정 이름, 지역 여러 개·서울 구, 요금·주소·지도)을 추가하고, 후기 요약에 근거 링크 1~2개를 함께 적도록 에이전트 지시를 보강한 최종 코드로 다시 실행한 결과다. 같은 세트·같은 심판으로 18/18을 유지해 회귀가 없음을 확인했다.

- 실행: 2026-11-12 09:55 (Asia/Seoul) · 모델: `global.anthropic.claude-haiku-4-5-20251001-v1:0`
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
