# 클린 환경 재현용. 키는 이미지에 넣지 않고 실행할 때 --env-file .env 로 전달한다.
#   docker build -t exhibition-note .
#   docker run --rm -p 8000:8000 --env-file .env exhibition-note            # API  (POST /query)
#   docker run --rm -p 8501:8501 --env-file .env exhibition-note app        # Streamlit 화면
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY src/ src/
COPY data/corpus.jsonl data/corpus_meta.json data/
COPY run.sh .
RUN sed -i 's/\r$//' run.sh && chmod +x run.sh

EXPOSE 8000 8501
ENTRYPOINT ["./run.sh"]
CMD ["api"]
