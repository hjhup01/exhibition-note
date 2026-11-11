"""설정과 오늘 날짜. 오늘 날짜는 today_kst() 한 곳에서만 만든다."""
import logging
import os
from datetime import date, datetime
from zoneinfo import ZoneInfo

DEFAULT_BEDROCK_MODEL_ID = "apac.anthropic.claude-3-5-sonnet-20241022-v2:0"
DEFAULT_DB_PATH = "./data/exhibitions.db"
CULTURE_PAGE_SIZE = 100
TIMEOUT_SECONDS = 10


def today_kst() -> date:
    """Asia/Seoul 기준 현재 날짜."""
    return datetime.now(ZoneInfo("Asia/Seoul")).date()


def bedrock_model_id(env=None) -> str:
    env = os.environ if env is None else env
    return (env.get("BEDROCK_MODEL_ID") or "").strip() or DEFAULT_BEDROCK_MODEL_ID


def db_path(env=None) -> str:
    env = os.environ if env is None else env
    return (env.get("DB_PATH") or "").strip() or DEFAULT_DB_PATH


def bedrock_client_config(env=None) -> dict:
    """ChatBedrock 생성 인자: model_id와 botocore Config(제한시간 10초, 재시도 없음)."""
    from botocore.config import Config

    return {
        "model_id": bedrock_model_id(env),
        "config": Config(connect_timeout=TIMEOUT_SECONDS, read_timeout=TIMEOUT_SECONDS,
                         retries={"total_max_attempts": 1}),
    }


SECRET_ENV_KEYS = (
    "CULTURE_API_KEY", "SERVICE_KEY", "KAKAO_REST_API_KEY", "GOOGLE_CLIENT_SECRET",
    "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "LANGSMITH_API_KEY",
)
REDACTED = "***"
_LIBRARY_LOGGERS = ("requests", "urllib3", "botocore", "langchain", "langsmith")


def secret_values(env=None) -> list:
    env = os.environ if env is None else env
    values = {(env.get(k) or "").strip() for k in SECRET_ENV_KEYS}
    return sorted((v for v in values if v), key=len, reverse=True)


class SecretRedactionFilter(logging.Filter):
    """로그 레코드의 메시지·인자에서 비밀 값을 가린다."""

    def __init__(self, secrets):
        super().__init__()
        self.secrets = list(secrets)

    def _mask(self, text):
        for s in self.secrets:
            text = text.replace(s, REDACTED)
        return text

    def filter(self, record):
        try:
            message = record.getMessage()
        except Exception:
            message = str(record.msg)
        record.msg, record.args = self._mask(message), None
        if record.exc_info:
            record.exc_text = None
            record.exc_info = None
        return True


def install_secret_redaction(env=None) -> SecretRedactionFilter:
    """루트 핸들러와 라이브러리 로거에 필터를 설치한다(이미 설치된 곳은 건너뜀)."""
    flt = SecretRedactionFilter(secret_values(env))
    targets = list(logging.getLogger().handlers) + [logging.getLogger(n) for n in _LIBRARY_LOGGERS]
    for t in targets:
        for old in [f for f in t.filters if isinstance(f, SecretRedactionFilter)]:
            t.removeFilter(old)
        t.addFilter(flt)
    return flt
