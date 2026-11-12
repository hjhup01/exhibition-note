"""특정 케이스를 여러 번 실행해 판정이 안정적인지 본다(보고서에는 쓰지 않음).

실행: python evaluation/check_case.py 3 --repeat 3
"""
import argparse
import csv
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_eval  # noqa: E402  (.env 읽기·경로 설정 포함)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("case_id")
    ap.add_argument("--repeat", type=int, default=3)
    args = ap.parse_args()
    os.environ["DB_PATH"] = str(run_eval.EVAL / "eval_records.db")
    run_eval.seed_records(os.environ["DB_PATH"])
    case = next(c for c in csv.DictReader(open(run_eval.EVAL / "test_queries.csv", encoding="utf-8"))
                if c["id"] == args.case_id)
    llm = run_eval.agent.make_llm()
    graph = run_eval.agent.build_graph(llm)
    today = run_eval.agent.config.today_kst().isoformat()
    passed = 0
    for i in range(args.repeat):
        r = run_eval.agent.run(case["input"], graph=graph)
        v = run_eval.judge_case(llm, today, case, r)
        passed += v["passed"]
        fails = [t["item"] for t in v["traits_judged"] + v["forbidden_judged"] if not t["ok"]] + v["missing_tools"]
        print(f"#{i + 1}: {'PASS' if v['passed'] else 'FAIL'} tools={r['tools_called']} fails={fails}")
    print(f"{case['id']}번: {passed}/{args.repeat} 통과")


if __name__ == "__main__":
    main()
