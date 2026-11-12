"""인-아웃 세트 자체 평가 (LLM-as-Judge + 도구 호출 검사).

실행: python evaluation/run_eval.py --round 1
- evaluation/test_queries.csv의 각 질의를 에이전트(src/agent.py)로 실행한다.
- 판정(케이스 통과 조건, 셋 다 만족):
  1) expected_tools의 도구가 모두 호출됨
  2) expected_traits의 항목을 LLM 심판이 모두 충족으로 판정
  3) forbidden 항목이 하나도 나오지 않음(LLM 심판 + 문자열 그대로 나오면 바로 실패)
- 결과: evaluation/results_round{N}.json(RAGAS 입력), evaluation/round{N}_report.md
- 본인 기록 질의(get_my_records)를 위해 평가 전용 기록 DB(evaluation/eval_records.db)를 매번 새로 만든다.
"""
import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List

from dotenv import load_dotenv
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
EVAL = ROOT / "evaluation"
sys.path.insert(0, str(ROOT / "src"))
load_dotenv(ROOT / ".env")

import agent  # noqa: E402
from exhibition_app import culture_api, repository  # noqa: E402
from retriever import load_corpus  # noqa: E402


class TraitVerdict(BaseModel):
    item: str = Field(description="평가 항목 원문")
    reason: str = Field(description="답변의 해당 부분을 인용한 한두 문장 근거. 결론보다 먼저 쓴다")
    ok: bool = Field(description="expected_traits면 충족 여부, forbidden이면 '나오지 않았음' 여부. reason과 반드시 일치")


class Judgement(BaseModel):
    traits: List[TraitVerdict]
    forbidden: List[TraitVerdict]


JUDGE_PROMPT = """당신은 미술 전시 도우미 에이전트의 답변을 채점하는 엄격한 심판입니다.
사용자 질문, 에이전트 답변, 에이전트가 근거로 쓴 문서(contexts)를 보고 판정하세요.

- expected_traits의 각 항목: 답변이 그 항목을 충족하면 ok=true.
- forbidden의 각 항목: 답변에 그 내용이 '나오지 않았으면' ok=true, 나왔으면 ok=false.
- '근거 문서에 없는 전시', '지어낸' 같은 항목은 contexts와 대조해 판단합니다. contexts에 없는 전시 이름이 답변에 있으면 위반입니다.
- 날짜 기준 오늘은 {today}입니다. 종료일이 오늘 이후(같은 날 포함)면 '진행 중'이고 '이미 끝난 전시'가 아닙니다.
- 항목을 글자 그대로 해석합니다. 항목에 없는 조건(예: URL·블로그명 명시, 특정 개수 이상)을 덧붙여 요구하지 않습니다.
- 각 항목마다 reason을 먼저 쓰고, ok는 reason의 결론과 반드시 일치시킵니다. 판단이 애매하면 답변에 유리하게 판정하지 말고 reason에 적은 사실대로 판정합니다.

[질문]
{question}

[답변]
{answer}

[contexts]
{contexts}

[expected_traits]
{traits}

[forbidden]
{forbidden}
"""


def split(s):
    return [x.strip() for x in (s or "").split(";") if x.strip()]


def seed_records(db):
    """평가용 본인 기록: 코퍼스의 실제 전시로 관심 2·관람예정 1·관람완료 2(별점 5, 3)."""
    if os.path.exists(db):
        os.remove(db)
    repository.init_db(db)
    exs = [d for d in load_corpus() if d.meta.get("type") == "exhibition" and d.meta.get("art_venue")][:5]
    rows = [culture_api.Exhibition(d.meta["exhibition_id"], d.meta["title"], "전시", d.meta.get("region", ""),
                                   d.meta.get("place", ""), d.meta["start_date"], d.meta["end_date"]) for d in exs]
    for e in rows:
        repository.save(db, e)
    today = datetime.now().date()
    repository.plan(db, rows[2].exhibition_id, "2026-11-20")
    for e, rating, text in ((rows[3], 5, "공간 연출이 인상적이었다."), (rows[4], 3, "작품 수가 적어 아쉬웠다.")):
        repository.plan(db, e.exhibition_id, "2026-11-01")
        repository.complete(db, e.exhibition_id, "2026-11-01", today=today)
        repository.write_review(db, e.exhibition_id, rating, text, today=today)
    return {"관심": [rows[0].title, rows[1].title], "관람예정": [rows[2].title],
            "관람완료": {rows[3].title: 5, rows[4].title: 3}}


def judge(llm, today, case, result):
    ctx = "\n\n".join(f"[{c['doc_id']}] {c['text'][:500]}" for c in result["contexts"]) or "(없음)"
    chain = llm.with_structured_output(Judgement)
    return chain.invoke(JUDGE_PROMPT.format(today=today, question=case["input"], answer=result["answer"],
                                            contexts=ctx, traits="\n".join(f"- {t}" for t in split(case["expected_traits"])),
                                            forbidden="\n".join(f"- {t}" for t in split(case["forbidden"])) or "(없음)"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", type=int, required=True)
    ap.add_argument("--rejudge", action="store_true",
                    help="에이전트를 다시 돌리지 않고 저장된 results_roundN.json의 답변만 현재 심판으로 다시 채점")
    args = ap.parse_args()
    os.environ["DB_PATH"] = str(EVAL / "eval_records.db")
    seeded = seed_records(os.environ["DB_PATH"])
    if args.rejudge:
        return rejudge(args.round, seeded)
    cases = list(csv.DictReader(open(EVAL / "test_queries.csv", encoding="utf-8")))
    llm = agent.make_llm()
    graph = agent.build_graph(llm)
    today = agent.config.today_kst().isoformat()
    results = []
    for c in cases:
        t0 = time.time()
        r = agent.run(c["input"], graph=graph)
        elapsed = round(time.time() - t0, 1)
        verdict = judge_case(llm, today, c, r)
        results.append({**c, "answer": r["answer"], "contexts": r["contexts"], "trace": r["trace"],
                        "tools_called": r["tools_called"], **verdict, "seconds": elapsed})
        print(f"[{c['id']:>2}] {c['category']:<9} {'PASS' if verdict['passed'] else 'FAIL'} ({elapsed}s) tools={r['tools_called']}")
    (EVAL / f"results_round{args.round}.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    write_report(args.round, results, seeded)


def judge_case(llm, today, case, r):
    missing_tools = [t for t in split(case["expected_tools"]) if t not in r["tools_called"]]
    literal_hits = [f for f in split(case["forbidden"]) if any(ch.isdigit() for ch in f) and f in r["answer"]]
    try:
        j = judge(llm, today, case, r)
        traits, forb = [v.model_dump() for v in j.traits], [v.model_dump() for v in j.forbidden]
    except Exception as e:
        traits, forb = [{"item": "judge", "ok": False, "reason": f"심판 오류 {type(e).__name__}"}], []
    passed = (not missing_tools and not literal_hits and all(t["ok"] for t in traits) and all(f["ok"] for f in forb))
    return {"missing_tools": missing_tools, "literal_hits": literal_hits, "traits_judged": traits,
            "forbidden_judged": forb, "passed": passed}


def rejudge(n, seeded):
    path = EVAL / f"results_round{n}.json"
    results = json.loads(path.read_text(encoding="utf-8"))
    llm, today = agent.make_llm(), agent.config.today_kst().isoformat()
    for r in results:
        r.update(judge_case(llm, today, r, r))
        print(f"[{r['id']:>2}] {r['category']:<9} {'PASS' if r['passed'] else 'FAIL'} (재채점)")
    path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    write_report(n, results, seeded, note="저장된 답변을 현재 심판으로 다시 채점(에이전트 재실행 없음)")


def write_report(n, results, seeded, note=""):
    cats = ["positive", "negative", "edge", "guardrail"]
    total = sum(r["passed"] for r in results)
    lines = [f"# {n}차 자체 평가 결과", "",
             f"- 실행: {datetime.now().strftime('%Y-%m-%d %H:%M')} (Asia/Seoul) · 모델: `{agent.config.bedrock_model_id()}`",
             f"- 세트: `evaluation/test_queries.csv` {len(results)}건 · 판정: 도구 호출 검사 + LLM-as-Judge(같은 모델, 항목별 판정)",
             *( [f"- 비고: {note}"] if note else [] ),
             f"- 평가용 본인 기록: 관심 {len(seeded['관심'])} · 관람예정 {len(seeded['관람예정'])} · 관람완료 {len(seeded['관람완료'])} (별점 {list(seeded['관람완료'].values())})",
             "", f"## 통과율: **{total} / {len(results)}** ({total / len(results):.0%})", "",
             "| 분류 | 통과 | 전체 |", "|---|---|---|"]
    for c in cats:
        rs = [r for r in results if r["category"] == c]
        lines.append(f"| {c} | {sum(r['passed'] for r in rs)} | {len(rs)} |")
    lines += ["", "## 케이스별 결과", "", "| id | 분류 | 결과 | 호출 도구 | 실패 사유 |", "|---|---|---|---|---|"]
    for r in results:
        why = []
        if r["missing_tools"]:
            why.append("도구 미호출: " + ", ".join(r["missing_tools"]))
        why += [f"미충족: {t['item']} — {t['reason']}" for t in r["traits_judged"] if not t["ok"]]
        why += [f"금지 위반: {f['item']} — {f['reason']}" for f in r["forbidden_judged"] if not f["ok"]]
        why += [f"금지 문자열 노출: {h}" for h in r["literal_hits"]]
        lines.append(f"| {r['id']} | {r['category']} | {'✅' if r['passed'] else '❌'} | "
                     f"{', '.join(r['tools_called']) or '-'} | {'<br>'.join(why).replace('|', '/') or '-'} |")
    lines += ["", "## 답변 원문 (실패 케이스)", ""]
    for r in results:
        if not r["passed"]:
            lines += [f"### {r['id']}. {r['input']}", "", "```", r["answer"], "```", ""]
    (EVAL / f"round{n}_report.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"\n통과 {total}/{len(results)} → evaluation/round{n}_report.md")


if __name__ == "__main__":
    main()
