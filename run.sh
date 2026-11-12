#!/usr/bin/env sh
# 사용법: ./run.sh [api|app|eval N|corpus|test]
#   api     : POST /query API (http://localhost:8000/docs)
#   app     : Streamlit 화면 (http://localhost:8501)
#   eval N  : N차 인-아웃 세트 자체 평가 (evaluation/roundN_report.md)
#   corpus  : RAG 코퍼스 다시 만들기 (data/corpus.jsonl)
#   test    : 단위·화면 테스트
set -e
cd "$(dirname "$0")"
case "${1:-api}" in
  api)    exec uvicorn api:app --app-dir src --host 0.0.0.0 --port "${PORT:-8000}" ;;
  app)    exec streamlit run src/app.py --server.port "${PORT:-8501}" --server.address 0.0.0.0 --server.headless true ;;
  eval)   exec python evaluation/run_eval.py --round "${2:-1}" ;;
  corpus) exec python src/build_corpus.py ;;
  test)   exec python -m pytest -q ;;
  *)      echo "사용법: ./run.sh [api|app|eval N|corpus|test]"; exit 1 ;;
esac
