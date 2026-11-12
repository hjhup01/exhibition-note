"""RAGAS 지표 계산 (run_eval.py 결과를 입력으로 사용).

RAGAS 0.4.3은 최신 LangChain(1.x)과 호환되지 않아, 에이전트와 분리된 환경에서 실행한다:
  uv run --no-project --python 3.12 --with "ragas==0.4.3" --with "langchain-community<0.4" \
      --with "langchain-aws<1" --with python-dotenv python evaluation/ragas_eval.py --round 1
- 대상: 근거 문서(contexts)가 있는 케이스(도구를 호출해 답한 positive·edge·negative). 거절로 끝난 guardrail 케이스는 제외.
- 지표: context_recall · context_precision · faithfulness · answer_relevancy
- 심판 LLM: Bedrock Claude Haiku 4.5 / 임베딩: Bedrock Titan Text Embeddings v2
- 결과: evaluation/ragas_round{N}.json, 그리고 round{N}_report.md 끝에 표를 덧붙인다.
"""
import argparse
import json
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
EVAL = ROOT / "evaluation"
load_dotenv(ROOT / ".env")
os.environ["LANGSMITH_TRACING"] = "false"   # 채점 호출은 에이전트 트레이스와 섞지 않는다

# context_recall에 쓰는 기준 답변(reference). 실시간 데이터라 개별 전시명 대신 답이 담아야 할 사실을 적는다.
REFERENCES = {
    "1": "서울에서 현재 진행 중인 미술관·갤러리 전시 세 개를 전시 제목, 장소, 전시 기간과 함께 추천한다.",
    "2": "부산에서 현재 진행 중인 전시를 전시 제목, 장소, 전시 기간과 함께 알려 준다.",
    "3": "패트릭 블랑의 수직정원은 부산현대미술관에 있는 상설 전시로, 약 2만 9천 그루의 식물로 이루어진 수직 정원이며 관람객 후기에서 공간 연출이 인상적이라고 소개된다.",
    "4": "서울에서 아직 시작하지 않은 진행예정 전시를 시작일과 함께 알려 준다.",
    "5": "국립현대미술관(서울관·과천관·청주관 등)에서 열리는 전시를 전시 기간과 함께 알려 준다.",
    "6": "사용자 본인의 관심 목록에 저장된 전시 두 개의 제목을 알려 준다.",
    "7": "사용자가 관람완료한 전시 중 별점 5점을 준 전시가 가장 높으며, 그 전시의 제목과 별점을 알려 준다.",
    "9": "제주에서 열리는 공룡 화석 전시는 찾지 못했으며 다른 지역이나 키워드로 다시 찾아볼 것을 제안한다.",
    "12": "서울의 미술관·갤러리에서 열리는 전시를 제목과 장소와 함께 알려 준다.",
    "13": "모네와 관련된 전시를 찾아 알려 주거나, 찾지 못했다면 다른 검색 조건을 제안한다.",
    "14": "패트릭 블랑 수직정원 전시는 부산현대미술관에서 2028년 12월 31일까지 열리며, 후기에서는 2만 9천 그루 식물로 이루어진 수직 정원이 소개된다.",
    "15": "부산에서 열리는 전시를 제목과 장소와 함께 추천한다.",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", type=int, required=True)
    ap.add_argument("--report-only", action="store_true", help="계산 없이 저장된 ragas_roundN.json을 보고서에 다시 붙인다")
    args = ap.parse_args()
    if args.report_only:
        saved = json.loads((EVAL / f"ragas_round{args.round}.json").read_text(encoding="utf-8"))
        return append_report(args.round, saved["summary"], saved["cases"], saved.get("model", "global.anthropic.claude-haiku-4-5-20251001-v1:0"))

    from langchain_aws import BedrockEmbeddings, ChatBedrockConverse
    from ragas import EvaluationDataset, evaluate
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from ragas.llms import LangchainLLMWrapper
    from ragas.metrics import answer_relevancy, context_precision, context_recall, faithfulness
    from ragas.run_config import RunConfig

    region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
    model = os.environ.get("BEDROCK_MODEL_ID") or "global.anthropic.claude-haiku-4-5-20251001-v1:0"
    llm = LangchainLLMWrapper(ChatBedrockConverse(model=model.strip(), region_name=region, temperature=0))
    emb = LangchainEmbeddingsWrapper(BedrockEmbeddings(model_id="amazon.titan-embed-text-v2:0", region_name=region))

    results = json.loads((EVAL / f"results_round{args.round}.json").read_text(encoding="utf-8"))
    rows = [r for r in results if r["contexts"] and r["id"] in REFERENCES]
    ds = EvaluationDataset.from_list([{"user_input": r["input"], "response": r["answer"],
                                       "retrieved_contexts": [c["text"] for c in r["contexts"]],
                                       "reference": REFERENCES[r["id"]]} for r in rows])
    out = evaluate(ds, metrics=[context_recall, context_precision, faithfulness, answer_relevancy],
                   llm=llm, embeddings=emb, run_config=RunConfig(max_workers=4, timeout=120), show_progress=False)
    df = out.to_pandas()
    names = ["context_recall", "context_precision", "faithfulness", "answer_relevancy"]
    summary = {n: round(float(df[n].dropna().mean()), 3) for n in names if n in df}
    per_case = [{"id": r["id"], **{n: (None if df[n].isna()[i] else round(float(df[n][i]), 3)) for n in names if n in df}}
                for i, r in enumerate(rows)]
    (EVAL / f"ragas_round{args.round}.json").write_text(
        json.dumps({"summary": summary, "cases": per_case, "n": len(rows), "model": model.strip()}, ensure_ascii=False, indent=2), encoding="utf-8")

    append_report(args.round, summary, per_case, model.strip())
    print(json.dumps(summary, ensure_ascii=False))


def append_report(n, summary, per_case, model):
    names = ["context_recall", "context_precision", "faithfulness", "answer_relevancy"]
    lines = ["", "## RAGAS 지표", "",
             f"- 대상: 근거 문서가 있는 {len(per_case)}건 (id {', '.join(pc['id'] for pc in per_case)}) · "
             f"심판 `{model}` · 임베딩 `amazon.titan-embed-text-v2:0`", "",
             "| 지표 | 평균 |", "|---|---|"] + [f"| {k} | {v:.2f} |" for k, v in summary.items()]
    lines += ["", "| id | " + " | ".join(names) + " |", "|" + "---|" * (len(names) + 1)]
    for pc in per_case:
        lines.append(f"| {pc['id']} | " + " | ".join("-" if pc.get(k) is None else f"{pc[k]:.2f}" for k in names) + " |")
    report = EVAL / f"round{n}_report.md"
    marker = "\n## RAGAS 지표"
    text = report.read_text(encoding="utf-8").split(marker)[0]
    report.write_text(text + "\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
