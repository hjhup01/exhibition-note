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
