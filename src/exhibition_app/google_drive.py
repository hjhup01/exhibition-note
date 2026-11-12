"""구글 로그인(OAuth 2.0)과 사용자 드라이브의 '전시노트 기록' 시트 읽기·쓰기.

- 권한(scope)은 openid·email과 drive.file(이 앱이 만든 파일만)만 요청한다.
- 로그인 정보(access token)는 서버에 저장하지 않고 Streamlit 세션에만 둔다.
- OAuth state는 세션이 아니라 서명(HMAC)으로 검증한다. 구글에서 돌아오면 새 세션이 되기 때문이다.
- 모든 호출은 10초 제한이며, 실패하면 GoogleError(사용자용 한국어 문구)를 던진다. 토큰·비밀값은 메시지에 넣지 않는다.
"""
import base64
import hashlib
import hmac
import json
import os
import time
from urllib.parse import urlencode

import requests

from . import messages

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
DRIVE_FILES_URL = "https://www.googleapis.com/drive/v3/files"
SHEETS_URL = "https://sheets.googleapis.com/v4/spreadsheets"
SCOPES = ("openid", "email", "https://www.googleapis.com/auth/drive.file")
TIMEOUT_SECONDS = 10
STATE_MAX_AGE_SECONDS = 1800  # 2단계 인증 등으로 시간이 걸려도 만료되지 않게 30분
DEFAULT_REDIRECT_URI = "http://localhost:8501"

SPREADSHEET_TITLE = "전시노트 기록"
SHEET_NAME = "saved_exhibition"
COLUMNS = ("exhibition_id", "title", "category", "region", "place", "start_date", "end_date",
           "status", "planned_visit_date", "actual_visit_date", "review_rating", "review_text",
           "created_at", "updated_at")
_INT_COLUMNS = {"review_rating"}
_LAST_COL = chr(ord("A") + len(COLUMNS) - 1)  # 'N'


class GoogleError(Exception):
    """구글 로그인·드라이브 호출 실패. str()은 화면에 그대로 보여 줄 한국어 문구다."""


class AuthExpired(GoogleError):
    """access token이 만료·취소됨(401). 다시 로그인해야 한다."""


# ---------- 설정 ----------

def oauth_settings(env=None):
    """(client_id, client_secret, redirect_uri). 클라이언트 ID·비밀값이 없으면 None(구글 저장 꺼짐)."""
    env = os.environ if env is None else env
    cid = (env.get("GOOGLE_CLIENT_ID") or "").strip()
    secret = (env.get("GOOGLE_CLIENT_SECRET") or "").strip()
    if not cid or not secret:
        return None
    redirect = (env.get("GOOGLE_REDIRECT_URI") or "").strip() or DEFAULT_REDIRECT_URI
    return cid, secret, redirect


# ---------- 로그인 ----------

def make_state(secret, now=None):
    ts = str(int(now if now is not None else time.time()))
    sig = hmac.new(secret.encode(), ts.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{ts}.{sig}"


def verify_state(state, secret, now=None):
    """서명이 맞고 10분 안에 만든 state인지."""
    try:
        ts, sig = str(state).split(".", 1)
        age = (now if now is not None else time.time()) - int(ts)
    except (ValueError, TypeError):
        return False
    expected = hmac.new(secret.encode(), ts.encode(), hashlib.sha256).hexdigest()[:32]
    return hmac.compare_digest(sig, expected) and 0 <= age <= STATE_MAX_AGE_SECONDS


def auth_url(client_id, redirect_uri, state):
    return AUTH_URL + "?" + urlencode({
        "client_id": client_id, "redirect_uri": redirect_uri, "response_type": "code",
        "scope": " ".join(SCOPES), "state": state, "access_type": "online",
        "include_granted_scopes": "true"})
    # prompt=select_account를 빼서, 한 번 허용한 계정은 다음 로그인 때 계정 선택·동의 없이 바로 돌아오게 한다


_IN_APP_MARKERS = ("kakaotalk", "naver(inapp", "instagram", "fban", "fbav", "line/", "daumapps", "everytimeapp",
                   "; wv)")


def is_in_app_browser(user_agent):
    """카카오톡·인스타그램·네이버 앱 등 앱 안의 브라우저(WebView)인지. 구글은 이런 곳에서 로그인을 막는다
    (오류: 403 disallowed_useragent)."""
    ua = (user_agent or "").lower()
    return any(m in ua for m in _IN_APP_MARKERS)


def redirect_host_mismatch(request_host, redirect_uri):
    """지금 접속한 주소(Host)와 로그인 후 돌아올 주소(GOOGLE_REDIRECT_URI)의 호스트가 다른지.
    다르면 로그인 후 다른 주소로 돌아가거나 구글이 redirect_uri_mismatch로 막는다."""
    from urllib.parse import urlparse
    if not request_host or not redirect_uri:
        return False
    def norm(netloc):  # localhost와 127.0.0.1은 같은 곳으로 본다
        return netloc.strip().lower().replace("127.0.0.1", "localhost")

    host = norm(request_host.split(",")[0])
    want = norm(urlparse(redirect_uri).netloc or "")
    return bool(want) and host != want


def login_error_message(error):
    """구글이 ?error=…로 돌려보낸 이유를 사용자용 문구로."""
    if error == "access_denied":
        return messages.GOOGLE_ACCESS_DENIED
    return messages.GOOGLE_LOGIN_FAILED


def _email_from_id_token(id_token):
    try:
        payload = id_token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload)).get("email", "")
    except Exception:
        return ""


def exchange_code(code, client_id, client_secret, redirect_uri, post=None):
    """인가 코드를 access token으로 바꾼다. 반환: {'access_token', 'email'}."""
    post = post or requests.post
    try:
        resp = post(TOKEN_URL, data={"code": code, "client_id": client_id, "client_secret": client_secret,
                                     "redirect_uri": redirect_uri, "grant_type": "authorization_code"},
                    timeout=TIMEOUT_SECONDS)
        data = resp.json() if resp.status_code == 200 else None
    except Exception:
        data = None
    if not data or not data.get("access_token"):
        raise GoogleError(messages.GOOGLE_LOGIN_FAILED)
    granted = set((data.get("scope") or "").split())
    if granted and SCOPES[2] not in granted:
        raise GoogleError(messages.GOOGLE_SCOPE_MISSING)
    return {"access_token": data["access_token"], "email": _email_from_id_token(data.get("id_token", ""))}


# ---------- 시트 ----------

def _cell(col, value):
    if value is None:
        return ""
    return value if col in _INT_COLUMNS else str(value)


def rows_to_values(rows):
    return [list(COLUMNS)] + [[_cell(c, r.get(c)) for c in COLUMNS] for r in rows]


def values_to_rows(values):
    """시트 값(머리글 포함)을 dict 목록으로. 빈 칸은 None, 별점은 정수. exhibition_id가 없는 줄은 버린다."""
    if not values:
        return []
    header = [str(h).strip() for h in values[0]]
    rows = []
    for raw in values[1:]:
        r = {}
        for c in COLUMNS:
            v = raw[header.index(c)] if c in header and header.index(c) < len(raw) else ""
            if v == "" or v is None:
                r[c] = None
            elif c in _INT_COLUMNS:
                try:
                    r[c] = int(float(v))
                except (TypeError, ValueError):
                    r[c] = None
            else:
                r[c] = str(v)
        if r["exhibition_id"]:
            rows.append(r)
    return rows


class SheetClient:
    """한 사용자의 access token으로 그 사람 드라이브의 '전시노트 기록' 시트를 다룬다."""

    def __init__(self, access_token, http=None):
        self._headers = {"Authorization": f"Bearer {access_token}"}
        self._http = http or requests

    def _call(self, method, url, **kw):
        try:
            resp = self._http.request(method, url, headers=self._headers, timeout=TIMEOUT_SECONDS, **kw)
        except Exception:
            raise GoogleError(messages.GOOGLE_SHEET_FAILED) from None
        if resp.status_code == 401:
            raise AuthExpired(messages.GOOGLE_LOGIN_EXPIRED)
        if resp.status_code >= 400:
            raise GoogleError(messages.GOOGLE_SHEET_FAILED)
        try:
            return resp.json() if resp.content else {}
        except ValueError:
            raise GoogleError(messages.GOOGLE_SHEET_FAILED) from None

    def find_or_create(self):
        """사용자 드라이브에서 '전시노트 기록'을 찾고, 없으면 머리글만 있는 새 시트를 만든다. spreadsheetId 반환."""
        q = (f"name = '{SPREADSHEET_TITLE}' and mimeType = 'application/vnd.google-apps.spreadsheet'"
             " and trashed = false")
        found = self._call("GET", DRIVE_FILES_URL, params={"q": q, "spaces": "drive",
                                                            "fields": "files(id,name)", "pageSize": 10})
        files = found.get("files") or []
        if files:
            return files[0]["id"]
        created = self._call("POST", SHEETS_URL, json={
            "properties": {"title": SPREADSHEET_TITLE},
            "sheets": [{"properties": {"title": SHEET_NAME}}]})
        sid = created.get("spreadsheetId")
        if not sid:
            raise GoogleError(messages.GOOGLE_SHEET_FAILED)
        self.write_rows(sid, [])
        return sid

    def read_rows(self, spreadsheet_id):
        data = self._call("GET", f"{SHEETS_URL}/{spreadsheet_id}/values/{SHEET_NAME}!A1:{_LAST_COL}",
                          params={"valueRenderOption": "UNFORMATTED_VALUE"})
        return values_to_rows(data.get("values") or [])

    def write_rows(self, spreadsheet_id, rows):
        """시트 내용을 rows로 통째로 바꾼다(머리글 + 행). 기록 수가 적은 개인용이라 전체를 다시 쓴다."""
        base = f"{SHEETS_URL}/{spreadsheet_id}/values"
        self._call("POST", f"{base}/{SHEET_NAME}!A:{_LAST_COL}:clear", json={})
        self._call("PUT", f"{base}/{SHEET_NAME}!A1", params={"valueInputOption": "RAW"},
                   json={"values": rows_to_values(rows)})
