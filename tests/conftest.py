"""모든 테스트 공통: 실제 .env의 구글 로그인 설정이 테스트에 섞이지 않게 한다.

app.py는 시작할 때 load_dotenv()로 .env를 읽는다. load_dotenv는 이미 있는 환경변수는 덮어쓰지 않으므로,
여기서 빈 값으로 먼저 정해 두면 테스트는 기본적으로 로컬 SQLite 모드로 돈다.
구글 모드를 시험하는 테스트는 monkeypatch.setenv로 값을 다시 넣는다.
"""
import pytest


@pytest.fixture(autouse=True)
def _no_google_from_dotenv(monkeypatch):
    for key in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REDIRECT_URI"):
        monkeypatch.setenv(key, "")


@pytest.fixture(autouse=True)
def _no_real_detail_api(monkeypatch):
    """전시 상세(요금·주소) 조회는 실제 API를 부르지 않게 한다. 상세를 시험하는 테스트는 직접 바꿔 넣는다."""
    from exhibition_app import culture_api
    monkeypatch.setattr(culture_api, "fetch_detail", lambda *a, **k: None)


@pytest.fixture(autouse=True)
def _fresh_llm_status():
    """AI 인증 실패 기록이 테스트 사이에 남지 않게 한다."""
    from exhibition_app import llm_status
    llm_status.reset()
    yield
    llm_status.reset()


@pytest.fixture(autouse=True)
def _no_native_login_from_secrets(monkeypatch):
    """실제 .streamlit/secrets.toml의 [auth](내장 로그인) 설정이 테스트에 섞이지 않게 한다."""
    from exhibition_app import native_auth
    monkeypatch.setattr(native_auth, "enabled", lambda: False)
