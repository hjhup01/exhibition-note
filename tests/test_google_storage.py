"""구글 로그인·사용자 드라이브 시트 저장 (가짜 구글 응답, 네트워크 없음)."""
import base64
import json
from datetime import date
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from exhibition_app import config, culture_api, google_drive, messages, repository, search_api, storage, summarizer
from exhibition_app.culture_api import Exhibition

TODAY = date(2026, 11, 11)
APP = str(Path(__file__).resolve().parent.parent / "src" / "app.py")
SECRET = "client-secret-SENTINEL"
EX = Exhibition("1", "빛의 층위", "전시", "서울", "한강아트센터", "2026-10-02", "2027-01-18")


def id_token(email):
    body = base64.urlsafe_b64encode(json.dumps({"email": email}).encode()).decode().rstrip("=")
    return f"h.{body}.s"


# ---------- 설정·로그인 ----------

def test_oauth_settings_off_without_client_and_default_redirect():
    assert google_drive.oauth_settings({}) is None
    assert google_drive.oauth_settings({"GOOGLE_CLIENT_ID": "id"}) is None
    assert google_drive.oauth_settings({"GOOGLE_CLIENT_ID": "id", "GOOGLE_CLIENT_SECRET": "s"}) == \
        ("id", "s", "http://localhost:8501")
    assert google_drive.oauth_settings({"GOOGLE_CLIENT_ID": "id", "GOOGLE_CLIENT_SECRET": "s",
                                        "GOOGLE_REDIRECT_URI": "https://x.streamlit.app"})[2] == "https://x.streamlit.app"


def test_state_is_signed_and_expires():
    st_ = google_drive.make_state(SECRET, now=1000)
    assert google_drive.verify_state(st_, SECRET, now=1000 + 599)
    assert not google_drive.verify_state(st_, SECRET, now=1000 + google_drive.STATE_MAX_AGE_SECONDS + 1)
    assert not google_drive.verify_state(st_, "other-secret", now=1001)
    assert not google_drive.verify_state("1000.deadbeef", SECRET, now=1001)
    assert not google_drive.verify_state(None, SECRET)


def test_auth_url_requests_only_minimal_scopes():
    url = google_drive.auth_url("cid", "http://localhost:8501", "st")
    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "scope=openid+email+https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fdrive.file" in url
    assert "redirect_uri=http%3A%2F%2Flocalhost%3A8501" in url and "state=st" in url
    assert SECRET not in url


class Resp:
    def __init__(self, status=200, payload=None):
        self.status_code, self._payload = status, payload
        self.content = b"x" if payload is not None else b""

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def test_exchange_code_success_and_failures():
    ok = lambda *a, **k: Resp(200, {"access_token": "AT", "id_token": id_token("me@gmail.com"),
                                    "scope": "openid email https://www.googleapis.com/auth/drive.file"})
    assert google_drive.exchange_code("c", "id", SECRET, "r", post=ok) == {"access_token": "AT", "email": "me@gmail.com"}
    no_drive = lambda *a, **k: Resp(200, {"access_token": "AT", "scope": "openid email"})
    with pytest.raises(google_drive.GoogleError) as e:
        google_drive.exchange_code("c", "id", SECRET, "r", post=no_drive)
    assert str(e.value) == messages.GOOGLE_SCOPE_MISSING
    for bad in (lambda *a, **k: Resp(400, {"error": "invalid_grant"}),
                lambda *a, **k: (_ for _ in ()).throw(RuntimeError(SECRET))):
        with pytest.raises(google_drive.GoogleError) as e:
            google_drive.exchange_code("c", "id", SECRET, "r", post=bad)
        assert str(e.value) == messages.GOOGLE_LOGIN_FAILED and SECRET not in str(e.value)


# ---------- 시트 클라이언트 ----------

class FakeHttp:
    """Drive·Sheets REST를 흉내 낸다. files: 이름→id, sheets: id→values."""

    def __init__(self, existing=None, status=None):
        self.files = dict(existing or {})
        self.sheets = {sid: [list(google_drive.COLUMNS)] for sid in self.files.values()}
        self.calls = []
        self.status = status

    def request(self, method, url, headers=None, timeout=None, params=None, json=None):
        self.calls.append((method, url.split("googleapis.com")[1], params, json))
        assert headers["Authorization"] == "Bearer TOKEN" and timeout == 10
        if self.status:
            return Resp(self.status, {"error": {}})
        if url == google_drive.DRIVE_FILES_URL:
            assert "drive.file" not in (params or {}).get("q", "")
            return Resp(200, {"files": [{"id": i, "name": n} for n, i in self.files.items()]})
        if url == google_drive.SHEETS_URL and method == "POST":
            sid = f"S{len(self.files) + 1}"
            self.files[json["properties"]["title"]] = sid
            self.sheets[sid] = []
            return Resp(200, {"spreadsheetId": sid})
        sid = url.split("/spreadsheets/")[1].split("/")[0]
        if url.endswith(":clear"):
            self.sheets[sid] = []
            return Resp(200, {})
        if method == "PUT":
            self.sheets[sid] = json["values"]
            return Resp(200, {})
        return Resp(200, {"values": self.sheets[sid]} if self.sheets[sid] else {})


def test_find_or_create_creates_once_with_header():
    http = FakeHttp()
    client = google_drive.SheetClient("TOKEN", http=http)
    sid = client.find_or_create()
    assert http.files == {"전시노트 기록": sid}
    assert http.sheets[sid] == [list(google_drive.COLUMNS)]
    assert client.find_or_create() == sid and len(http.files) == 1  # 두 번째는 찾기만 한다


def test_rows_roundtrip_with_types_and_blanks():
    http = FakeHttp(existing={"전시노트 기록": "S9"})
    client = google_drive.SheetClient("TOKEN", http=http)
    rows = [{"exhibition_id": "319005", "title": "A", "category": "전시", "region": "서울", "place": "P",
             "start_date": "2026-01-01", "end_date": "2026-12-31", "status": "관람완료",
             "planned_visit_date": "2026-11-01", "actual_visit_date": "2026-11-02", "review_rating": 4,
             "review_text": "좋음", "created_at": "t1", "updated_at": "t2", "photo_ids": "[\"f1\", \"f2\"]"},
            {**{c: None for c in google_drive.COLUMNS}, "exhibition_id": "2", "title": "B", "status": "관심"}]
    client.write_rows("S9", rows)
    assert http.calls[-2][1].endswith(":clear") and http.calls[-1][2] == {"valueInputOption": "RAW"}
    back = client.read_rows("S9")
    assert back[0] == rows[0] and back[1]["planned_visit_date"] is None and back[1]["review_rating"] is None


def test_values_to_rows_tolerates_number_ids_float_rating_and_blank_lines():
    vals = [list(google_drive.COLUMNS), [319005, "A", "", "", "", "", "", "관심", "", "", 4.0],
            ["", "빈 줄"], []]
    rows = google_drive.values_to_rows(vals)
    assert len(rows) == 1 and rows[0]["exhibition_id"] == "319005" and rows[0]["review_rating"] == 4


@pytest.mark.parametrize("status,exc,msg", [(401, google_drive.AuthExpired, messages.GOOGLE_LOGIN_EXPIRED),
                                            (500, google_drive.GoogleError, messages.GOOGLE_SHEET_FAILED)])
def test_http_errors_become_messages(status, exc, msg):
    client = google_drive.SheetClient("TOKEN", http=FakeHttp(status=status))
    with pytest.raises(exc) as e:
        client.find_or_create()
    assert str(e.value) == msg and "TOKEN" not in str(e.value)


# ---------- 저장소(시트 + 기존 저장 규칙) ----------

class FakeClient:
    def __init__(self, rows=None):
        self.rows = [dict(r) for r in (rows or [])]
        self.writes = 0
        self.fail_write = False

    def find_or_create(self):
        return "SID"

    def read_rows(self, sid):
        return [dict(r) for r in self.rows]

    def write_rows(self, sid, rows):
        if self.fail_write:
            raise google_drive.GoogleError(messages.GOOGLE_SHEET_FAILED)
        self.writes += 1
        self.rows = [dict(r) for r in rows]


def test_sheet_storage_runs_existing_rules_and_pushes_changes():
    client, cache = FakeClient(), {}
    store = storage.SheetStorage(client, cache)
    db = store.prepare()
    assert repository.save(db, EX).ok
    store.after_write()
    assert repository.plan(db, "1", "2026-11-10").ok
    store.after_write()
    assert not repository.complete(db, "1", "2026-12-01", today=TODAY).ok  # 미래 실제 관람일은 규칙이 거부
    assert [(r["exhibition_id"], r["status"], r["planned_visit_date"]) for r in client.rows] == [("1", "관람예정", "2026-11-10")]
    assert client.writes == 2
    # 같은 세션에서는 다시 내려받지 않는다
    assert store.prepare() == db


def test_sheet_storage_push_failure_discards_local_change():
    client = FakeClient()
    store = storage.SheetStorage(client, {})
    db = store.prepare()
    repository.save(db, EX)
    client.fail_write = True
    with pytest.raises(google_drive.GoogleError):
        store.after_write()
    client.fail_write = False
    db2 = store.prepare()  # 시트(빈 상태)에서 다시 내려받는다
    assert repository.count(db2) == 0


# ---------- 화면 ----------

@pytest.fixture
def google_env(tmp_path, monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", SECRET)
    monkeypatch.setenv("DB_PATH", str(tmp_path / "local.db"))
    monkeypatch.setattr(config, "today_kst", lambda: TODAY)
    monkeypatch.setattr(culture_api, "fetch_exhibitions", lambda *a, **k: [EX])
    empty = {"items": [], "message": messages.NO_RESULT, "failed": False}
    monkeypatch.setattr(search_api, "load_related", lambda *a, **k: {"web": dict(empty), "blogs": dict(empty)})
    monkeypatch.setattr(summarizer, "summarize", lambda *a, **k: "")
    shared = FakeClient()
    monkeypatch.setattr(google_drive, "SheetClient", lambda token, http=None: shared)
    return shared, tmp_path


def texts(at):
    return [m.value for m in at.markdown] + [c.value for c in at.caption]


def test_not_logged_in_can_browse_but_not_save(google_env):
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    assert [b.label for b in at.sidebar.get("link_button")] == [messages.GOOGLE_LOGIN_BUTTON]
    assert messages.GOOGLE_LOGIN_NEEDED in texts(at)
    at.button(key="pick-1").click().run()
    assert at.button(key="save-1").disabled
    at.radio(key="page").set_value(messages.PAGE_MY).run()
    assert messages.GOOGLE_LOGIN_NEEDED in texts(at) and not at.tabs
    assert not (google_env[1] / "local.db").exists()  # 구글 모드에서는 로컬 DB를 만들지 않는다


def test_logged_in_saves_to_user_sheet_and_logout(google_env):
    shared, _ = google_env
    at = AppTest.from_file(APP, default_timeout=30)
    at.session_state["google"] = {"access_token": "AT", "email": "me@gmail.com"}
    at.run()
    assert "로그인: me@gmail.com" in [c.value for c in at.sidebar.caption]
    at.button(key="pick-1").click().run()
    at.button(key="save-1").click().run()
    assert not at.exception and messages.SAVED_DONE in texts(at)
    assert [(r["exhibition_id"], r["status"]) for r in shared.rows] == [("1", "관심")]
    at.radio(key="page").set_value(messages.PAGE_MY).run()
    at.button(key="plan-1").click().run()
    assert shared.rows[0]["status"] == "관람예정"
    at.sidebar.button(key="google-logout").click().run()
    assert "google" not in at.session_state


def test_push_failure_shows_message_and_keeps_sheet_unchanged(google_env):
    shared, _ = google_env
    shared.fail_write = True
    at = AppTest.from_file(APP, default_timeout=30)
    at.session_state["google"] = {"access_token": "AT", "email": "me@gmail.com"}
    at.run()
    at.button(key="pick-1").click().run()
    at.button(key="save-1").click().run()
    assert messages.GOOGLE_SHEET_FAILED in texts(at)
    assert shared.rows == []


def test_redirect_with_valid_state_logs_in(google_env, monkeypatch):
    monkeypatch.setattr(google_drive, "exchange_code",
                        lambda code, cid, secret, redirect: {"access_token": "AT", "email": f"{code}@gmail.com"})
    at = AppTest.from_file(APP, default_timeout=30)
    at.query_params["code"] = "me"
    at.query_params["state"] = google_drive.make_state(SECRET)
    at.run()
    assert not at.exception
    assert at.session_state["google"]["email"] == "me@gmail.com"


def test_redirect_with_bad_state_is_rejected(google_env, monkeypatch):
    monkeypatch.setattr(google_drive, "exchange_code", lambda *a: pytest.fail("must not exchange"))
    at = AppTest.from_file(APP, default_timeout=30)
    at.query_params["code"] = "me"
    at.query_params["state"] = "1.forged"
    at.run()
    assert "google" not in at.session_state
    assert messages.GOOGLE_STATE_INVALID in texts(at)


# ---------- 로그인 점검 보완 ----------

def test_auth_url_does_not_force_account_chooser():
    url = google_drive.auth_url("cid", "http://localhost:8501", "st")
    assert "prompt=" not in url


def test_state_valid_for_30_minutes():
    st_ = google_drive.make_state(SECRET, now=1000)
    assert google_drive.verify_state(st_, SECRET, now=1000 + 1799)
    assert not google_drive.verify_state(st_, SECRET, now=1000 + 1801)


@pytest.mark.parametrize("ua,expected", [
    ("Mozilla/5.0 (iPhone) AppleWebKit KAKAOTALK 10.4.5", True),
    ("Mozilla/5.0 (Linux; Android 14; SM-S918N; wv) AppleWebKit Chrome/120 Mobile", True),
    ("Mozilla/5.0 (iPhone) Instagram 300.0", True),
    ("Mozilla/5.0 (Windows NT 10.0) AppleWebKit Chrome/131 Safari/537.36 Edg/131", False),
    ("Mozilla/5.0 (iPhone) AppleWebKit Version/18.0 Mobile Safari/604.1", False),
    ("", False),
])
def test_in_app_browser_detection(ua, expected):
    assert google_drive.is_in_app_browser(ua) is expected


@pytest.mark.parametrize("host,redirect,expected", [
    ("localhost:8501", "http://localhost:8501", False),
    ("127.0.0.1:8501", "http://localhost:8501", False),
    ("localhost:8502", "http://localhost:8501", True),
    ("exhibition-note.streamlit.app", "https://exhibition-note.streamlit.app", False),
    ("exhibition-note.streamlit.app", "http://localhost:8501", True),
    ("", "http://localhost:8501", False),
])
def test_redirect_host_mismatch(host, redirect, expected):
    assert google_drive.redirect_host_mismatch(host, redirect) is expected


def test_login_error_messages():
    assert google_drive.login_error_message("access_denied") == messages.GOOGLE_ACCESS_DENIED
    assert google_drive.login_error_message("server_error") == messages.GOOGLE_LOGIN_FAILED


def test_redirect_success_shows_continue_here_message(google_env, monkeypatch):
    monkeypatch.setattr(google_drive, "exchange_code",
                        lambda code, cid, secret, redirect: {"access_token": "AT", "email": "me@gmail.com"})
    at = AppTest.from_file(APP, default_timeout=30)
    at.query_params["code"] = "c"
    at.query_params["state"] = google_drive.make_state(SECRET)
    at.run()
    assert messages.GOOGLE_LOGIN_DONE in texts(at)


def test_redirect_access_denied_explains_cause(google_env):
    at = AppTest.from_file(APP, default_timeout=30)
    at.query_params["error"] = "access_denied"
    at.run()
    assert "google" not in at.session_state and messages.GOOGLE_ACCESS_DENIED in texts(at)


def test_login_button_has_hint(google_env):
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert messages.GOOGLE_LOGIN_HINT in [c.value for c in at.sidebar.caption]


# ---------- 내장 로그인(st.login, 같은 창) ----------

@pytest.fixture
def native_env(google_env, monkeypatch):
    from exhibition_app import native_auth
    state = {"login": None, "calls": []}
    monkeypatch.setattr(native_auth, "enabled", lambda: True)
    monkeypatch.setattr(native_auth, "current_login", lambda: state["login"])
    monkeypatch.setattr(native_auth, "login", lambda: state["calls"].append("login"))
    monkeypatch.setattr(native_auth, "logout", lambda: state["calls"].append("logout"))
    return state, google_env[0]


def test_native_login_button_stays_in_same_window(native_env):
    state, _ = native_env
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    assert not at.sidebar.get("link_button")  # 새 창을 여는 링크 버튼이 아니다
    assert messages.GOOGLE_LOGIN_HINT_SAME_WINDOW in [c.value for c in at.sidebar.caption]
    at.sidebar.button(key="google-login").click().run()
    assert state["calls"] == ["login"]


def test_native_logged_in_saves_to_sheet_and_logs_out(native_env):
    state, shared = native_env
    state["login"] = {"access_token": "AT", "email": "me@gmail.com"}
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert "로그인: me@gmail.com" in [c.value for c in at.sidebar.caption]
    at.button(key="pick-1").click().run()
    at.button(key="save-1").click().run()
    assert not at.exception and [r["status"] for r in shared.rows] == ["관심"]
    at.sidebar.button(key="google-logout").click().run()
    assert "logout" in state["calls"]


def test_native_expired_token_asks_to_login_again(native_env):
    state, shared = native_env
    state["login"] = {"access_token": "OLD", "email": "me@gmail.com"}

    def expired():
        raise google_drive.AuthExpired(messages.GOOGLE_LOGIN_EXPIRED)
    shared.find_or_create = expired
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception and messages.GOOGLE_LOGIN_EXPIRED in texts(at)
    at.run()  # 같은 만료 토큰이 쿠키에 남아 있어도 로그인 버튼을 다시 보여 준다
    assert at.sidebar.button(key="google-login")


# ---------- 1시간 만료 → 자동 재로그인(반복 방지) ----------

def test_expires_soon_uses_id_token_exp():
    from exhibition_app import native_auth
    assert native_auth.expires_soon({"expires_at": 1000}, now=900) is True        # 100초 남음(< 180)
    assert native_auth.expires_soon({"expires_at": 1000}, now=500) is False       # 500초 남음
    assert native_auth.expires_soon({"expires_at": 1000}, now=999, margin=0) is False
    assert native_auth.expires_soon({"expires_at": 1000}, now=1001, margin=0) is True
    assert native_auth.expires_soon({"expires_at": None}, now=10**10) is False   # 모르면 만료로 보지 않는다


def test_native_auto_relogin_once_when_token_expires_during_use(native_env):
    import time
    state, shared = native_env
    state["login"] = {"access_token": "AT", "email": "me@gmail.com", "expires_at": int(time.time()) + 3600}
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception and state["calls"] == []  # 정상 사용 중
    state["login"]["expires_at"] = int(time.time()) + 60  # 1시간이 거의 다 됨
    at.run()
    assert state["calls"] == ["login"]  # 자동으로 구글 로그인으로 보냈다
    at.run()
    assert state["calls"] == ["login"]  # 같은 세션에서 다시 보내지 않는다(반복 방지)


def test_native_no_auto_relogin_on_fresh_visit_with_expired_cookie(native_env):
    """이미 만료된 쿠키로 새로 들어왔거나, 구글 화면에서 취소하고 돌아온 경우: 자동으로 보내지 않고 버튼을 보여 준다."""
    import time
    state, shared = native_env
    state["login"] = {"access_token": "OLD", "email": "me@gmail.com", "expires_at": int(time.time()) - 10}
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception and state["calls"] == []
    assert messages.GOOGLE_LOGIN_EXPIRED in texts(at)
    assert at.sidebar.button(key="google-login")


def test_native_auto_relogin_after_write_fails_with_expired_token(native_env):
    import time
    state, shared = native_env
    state["login"] = {"access_token": "AT", "email": "me@gmail.com", "expires_at": int(time.time()) + 3600}
    at = AppTest.from_file(APP, default_timeout=30).run()

    def expired(*a, **k):
        raise google_drive.AuthExpired(messages.GOOGLE_LOGIN_EXPIRED)
    shared.write_rows = expired  # 구글이 토큰을 일찍 취소한 경우 등
    at.button(key="pick-1").click().run()
    at.button(key="save-1").click().run()
    assert not at.exception
    assert state["calls"] == ["login"]
