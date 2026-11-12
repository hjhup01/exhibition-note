"""AI(Bedrock) 인증 상태: 키가 만료·취소되면 잠시 AI 호출을 건너뛴다.

인증 오류가 한 번 나면 COOLDOWN_SECONDS 동안은 요약·AI 도우미가 Bedrock을 부르지 않는다
(전시를 누를 때마다 실패를 몇 초씩 기다리지 않게). 그 뒤에는 다시 시도하므로,
키를 새로 넣으면(Streamlit Cloud Secrets 저장 → 앱 재시작) 바로 또는 늦어도 COOLDOWN 뒤에 되살아난다.
키는 모든 사용자가 같이 쓰므로 상태도 프로세스 전체에서 공유한다.
"""
import time

COOLDOWN_SECONDS = 600

# AWS가 '키가 틀림·만료·권한 없음'일 때 돌려주는 오류 코드·예외 이름
_AUTH_MARKERS = (
    "UnrecognizedClientException", "InvalidSignatureException", "ExpiredTokenException", "ExpiredToken",
    "AccessDeniedException", "InvalidClientTokenId", "SignatureDoesNotMatch", "NoCredentialsError",
    "PartialCredentialsError", "security token included in the request is invalid",
    "Unable to locate credentials",
)

_failed_at = None


def is_auth_error(exc):
    """예외(또는 그 원인 사슬)가 AWS 인증 오류이면 True. 네트워크·일시 오류는 False."""
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        text = f"{type(exc).__name__} {exc}"
        if any(m in text for m in _AUTH_MARKERS):
            return True
        exc = exc.__cause__ or exc.__context__
    return False


def mark_failed(now=None):
    global _failed_at
    _failed_at = time.monotonic() if now is None else now


def note(exc):
    """실패 예외를 보고 인증 오류면 기록한다. 인증 오류였는지 돌려준다."""
    if is_auth_error(exc):
        mark_failed()
        return True
    return False


def available(now=None):
    """지금 AI를 불러도 되는지. 인증 오류 뒤 COOLDOWN 동안은 False."""
    if _failed_at is None:
        return True
    now = time.monotonic() if now is None else now
    return now - _failed_at >= COOLDOWN_SECONDS


def reset():
    global _failed_at
    _failed_at = None
