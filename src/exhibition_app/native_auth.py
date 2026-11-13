"""Streamlit 내장 로그인(st.login)으로 같은 창에서 구글 로그인하기.

secrets.toml에 [auth] 항목이 있으면 이 방식을 쓴다.
- 로그인 버튼을 누르면 지금 창이 구글 로그인 화면으로 넘어갔다가 같은 창으로 돌아온다(새 창 없음).
- 로그인 정보는 Streamlit이 서명한 쿠키에 남아, 새로고침해도 로그인이 유지된다.
- 시트 읽기·쓰기에 필요한 access token은 [auth] expose_tokens = "access" 로 받는다.
  권한 범위는 [auth] client_kwargs.scope 에 drive.file 을 넣어 요청한다(예시는 secrets.toml.example).
[auth]가 없으면 기존 방식(google_drive.auth_url → ?code= 처리)을 그대로 쓴다.
"""
import time

import streamlit as st

# 구글 access token은 1시간짜리이고 Streamlit은 갱신 토큰을 주지 않는다.
# 만료 이만큼 전부터는 '곧 만료'로 보고, 앱을 쓰는 중이면 미리 다시 로그인시킨다(시트에 쓰다가 만료되지 않게).
RELOGIN_MARGIN_SECONDS = 180


def enabled():
    """secrets.toml(또는 배포 Secrets)에 [auth]의 client_id가 있는지."""
    try:
        auth = st.secrets.get("auth")
    except Exception:  # secrets 파일이 없으면 Streamlit이 예외를 던진다
        return False
    try:
        return bool(auth and auth.get("client_id"))
    except Exception:
        return False


def current_login():
    """로그인돼 있으면 {'access_token', 'email', 'expires_at'}, 아니면 None. 토큰이 노출 설정되지 않았으면 None.
    expires_at: 구글 ID 토큰의 만료 시각(exp, 초). access token과 같이 1시간 뒤다. 모르면 None."""
    try:
        if not st.user.is_logged_in:
            return None
        token = st.user.tokens.get("access") if hasattr(st.user.tokens, "get") else st.user.tokens["access"]
    except Exception:
        return None
    if not token:
        return None
    try:
        exp = int(st.user.get("exp"))
    except (TypeError, ValueError):
        exp = None
    return {"access_token": token, "email": st.user.get("email") or "", "expires_at": exp}


def expires_soon(login, now=None, margin=RELOGIN_MARGIN_SECONDS):
    """곧(margin초 안에) 만료되거나 이미 만료된 로그인인지. 만료 시각을 모르면 False."""
    exp = (login or {}).get("expires_at")
    if exp is None:
        return False
    return exp - (time.time() if now is None else now) <= margin


def login():
    st.login()


def logout():
    st.logout()
