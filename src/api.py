"""표준 API: POST /query → {answer, contexts, trace}.

실행: uvicorn api:app --app-dir src --port 8000
"""
from dotenv import load_dotenv
from fastapi import FastAPI
from pydantic import BaseModel, Field

load_dotenv()

import agent  # noqa: E402
from exhibition_app import config  # noqa: E402

config.install_secret_redaction()
app = FastAPI(title="전시노트 에이전트 API", version="1.0")


class QueryIn(BaseModel):
    question: str = Field(min_length=1, max_length=1000, description="사용자 질의")


class Context(BaseModel):
    doc_id: str
    text: str


class TraceStep(BaseModel):
    step: str
    input: str
    output: str


class QueryOut(BaseModel):
    answer: str
    contexts: list[Context]
    trace: list[TraceStep]


@app.post("/query", response_model=QueryOut)
def query(body: QueryIn):
    r = agent.run(body.question)
    return {"answer": r["answer"], "contexts": r["contexts"],
            "trace": [{"step": t["step"], "input": str(t["input"]), "output": str(t["output"])} for t in r["trace"]]}


@app.get("/health")
def health():
    return {"status": "ok"}
