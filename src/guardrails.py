"""가드레일(입력·출력 필터)과 개인정보 마스킹 미들웨어.

입력 단계 (LLM 호출 전)
- 프롬프트 인젝션·시스템 프롬프트 탈취 시도 → 차단
- API 키·비밀값 요청 → 차단
- 다른 사람의 기록·개인정보 요청 → 차단
- 질문 속 전화번호·이메일·주민등록번호 → 마스킹 후 진행(PII 미들웨어)
출력 단계 (답변 직전)
- 실제 비밀값(.env 키)이 섞이면 가림
- 시스템 프롬프트 문장이 새어 나가면 거절 문구로 바꿈
"""
import re
from dataclasses import dataclass

from exhibition_app import config

REFUSE_INJECTION = ("그 요청은 도와드릴 수 없습니다. 저는 미술 전시 찾기, 전시 관련 글 요약, "
                    "내 관람 기록 안내만 도와드려요. 전시에 대해 물어봐 주세요.")
REFUSE_SECRET = "API 키·비밀번호 같은 보안 정보는 알려 드릴 수 없습니다. 전시에 대해 물어봐 주세요."
REFUSE_OTHERS = ("다른 사람의 관람 기록이나 개인정보는 조회할 수 없습니다. "
                 "본인의 관람 기록이나 전시 정보는 도와드릴 수 있어요.")

_INJECTION = [r"(이전|위의|앞의|기존)\s*(의\s*)?(지시|명령|규칙|설정|프롬프트)[을를은는이가]?\s*(모두\s*)?(무시|잊|따르지)",
              r"시스템\s*프롬프트", r"system\s*prompt", r"ignore\s+(all\s+|the\s+)?(previous|prior|above)",
              r"(프롬프트|지시문|instructions?)[을를]?\s*(보여|알려|출력|공개|print|reveal|show)",
              r"개발자\s*모드", r"developer\s*mode", r"jailbreak", r"탈옥",
              r"너(의|는)?\s*(규칙|역할|정체).{0,6}(바꿔|무시|해제)", r"DAN\b"]
_SECRET = [r"api\s*키", r"api\s*key", r"액세스\s*키", r"access\s*key", r"secret", r"비밀\s*(번호|키|값)",
           r"토큰", r"token", r"\.env", r"환경\s*변수", r"password", r"자격\s*증명"]
_OTHERS = [r"(다른|남의|타인|친구|[가-힣]{2,4}\s*씨)\s*(사람|사용자|유저)?\s*(의)?\s*(관람\s*)?(기록|관람평|후기\s*기록|별점|저장)",
           r"(다른|남의|타인)\s*(사람|사용자).{0,8}(전화|연락처|이메일|주소|개인\s*정보)",
           r"(전화\s*번호|연락처|주민\s*(등록\s*)?번호|집\s*주소).{0,6}(알려|찾아|조회)"]

_PII = [(re.compile(r"\d{6}\s*-\s*[1-4]\d{6}"), "[주민번호]"),
        (re.compile(r"01[016789][-\s.]?\d{3,4}[-\s.]?\d{4}"), "[전화번호]"),
        (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[이메일]")]


@dataclass
class GuardResult:
    blocked: bool
    reason: str = "pass"          # pass | injection | secret | others_pii
    message: str = ""             # 차단 시 사용자에게 보여 줄 답변
    text: str = ""                # 통과 시 LLM에 넘길(마스킹된) 질문


def mask_pii(text):
    """전화번호·이메일·주민등록번호를 자리표시로 바꾼다. (마스킹된 문자열, 바꾼 개수)"""
    count = 0
    for pattern, label in _PII:
        text, n = pattern.subn(label, text)
        count += n
    return text, count


def _hit(patterns, text):
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


def check_input(question):
    q = (question or "").strip()
    if _hit(_INJECTION, q):
        return GuardResult(True, "injection", REFUSE_INJECTION)
    if _hit(_SECRET, q):
        return GuardResult(True, "secret", REFUSE_SECRET)
    if _hit(_OTHERS, q):
        return GuardResult(True, "others_pii", REFUSE_OTHERS)
    masked, _ = mask_pii(q)
    return GuardResult(False, "pass", "", masked)


def check_output(answer, system_prompt=""):
    """(안전한 답변, 바뀐 이유 또는 'pass')."""
    text = answer or ""
    for secret in config.secret_values():
        if secret and secret in text:
            text = text.replace(secret, config.REDACTED)
    if system_prompt:
        # 시스템 프롬프트의 긴 문장(25자 이상)이 그대로 나오면 유출로 본다
        for sentence in re.split(r"[.\n]", system_prompt):
            s = sentence.strip()
            if len(s) >= 25 and s in text:
                return REFUSE_INJECTION, "system_prompt_leak"
    text, n = mask_pii(text)
    return text, ("redacted" if text != (answer or "") or n else "pass")
