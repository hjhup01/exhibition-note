"""미술 전시 탐색·기록 앱 화면 (streamlit run app.py). 규칙은 exhibition_app 패키지에 있다."""
import html
from datetime import timedelta

import streamlit as st
from dotenv import load_dotenv

from exhibition_app import (config, culture_api, filters, google_drive, llm_status, messages, native_auth, photos,
                            repository, search_api, storage, summarizer)

_STORE = None  # 이번 실행의 저장소(LocalStorage 또는 SheetStorage). main()이 정한다.
NATIVE = "native"  # 구글 설정 대신 쓰는 표시: Streamlit 내장 로그인(st.login, 같은 창)을 쓴다


def _load_exhibitions():
    """세션 중 한 번만 조회한다. 실패하면 None."""
    if "exhibitions" not in st.session_state:
        try:
            st.session_state["exhibitions"] = culture_api.fetch_exhibitions()
        except culture_api.CultureApiError:
            st.session_state["exhibitions"] = None
    return st.session_state["exhibitions"]


def _retry_load():
    """'다시 불러오기': 실패로 기억해 둔 목록(현재·지난 전시)을 지워 다음 화면에서 다시 조회한다."""
    if st.session_state.get("exhibitions") is None:
        st.session_state.pop("exhibitions", None)
    cache = st.session_state.get("past_cache") or {}
    for k in [k for k, v in cache.items() if v[0] is None]:
        del cache[k]


def _period_text(e):
    return f"{e.start_date} ~ {e.end_date}"


DETAIL_CACHE_SIZE = 20  # 최근 본 전시 몇 개까지 상세(검색·요약)를 기억할지


def _detail_data(exhibition):
    """처음 보는 전시만 카카오 검색·LLM을 호출하고, 최근 본 전시 DETAIL_CACHE_SIZE개는 세션에 기억한다
    (다시 누르면 바로 열리고 AI 호출도 다시 하지 않는다)."""
    cache = st.session_state.get("detail_cache")
    if not isinstance(cache, dict) or "id" in cache:  # 예전 형식(전시 1개)이면 새로 시작
        cache = st.session_state["detail_cache"] = {}
    eid = exhibition.exhibition_id
    if eid not in cache:
        with st.spinner(messages.DETAIL_LOADING):
            # 제목 핵심어가 들어 있는 글만 보여 주고 요약한다(엉뚱한 전시 글이 요약되지 않게)
            related = search_api.load_related(exhibition.title, place=exhibition.place, only_relevant=True)
            summary = summarizer.summarize(related["web"]["items"], related["blogs"]["items"],
                                           title=exhibition.title)
            info = culture_api.fetch_detail(eid)
        cache[eid] = {"id": eid, "related": related, "summary": summary, "info": info}
        while len(cache) > DETAIL_CACHE_SIZE:  # 가장 오래 전에 본 것부터 버린다
            cache.pop(next(iter(cache)))
    else:
        cache[eid] = cache.pop(eid)  # 최근 본 것으로 뒤로 옮긴다
    return cache[eid]


def _flash(result, ok_text=None):
    """쓰기 결과를 다음 실행에서 보이도록 저장하고 다시 그린다(사이드바 건수 갱신)."""
    _remember_result(result, ok_text)
    st.rerun()


def _remember_result(result, ok_text=None):
    """쓰기 결과 문구를 다음 실행에서 보이도록 저장한다(버튼 콜백에서도 쓴다: 콜백 뒤에는 저절로 다시 그린다).
    실패하면 저장 규칙이 돌려준 문구를, 성공하면 ok_text를 보여 준다.
    구글 시트를 쓰는 중이면 성공한 변경을 시트에 올리고, 올리기에 실패하면 그 문구를 보여 준다."""
    message = result.message if not result.ok else ok_text
    if result.ok and _STORE is not None:
        try:
            _STORE.after_write()
        except google_drive.AuthExpired as e:
            _forget_login()
            message = str(e)
        except google_drive.GoogleError as e:
            message = str(e)
    st.session_state["flash"] = message


def _handle_google_redirect(settings):
    """구글 로그인 후 돌아온 주소(?code=…&state=… 또는 ?error=…)를 처리하고 주소를 깨끗이 한다."""
    qp = st.query_params
    if "code" not in qp and "error" not in qp:
        return
    cid, secret, redirect = settings
    code, state, error = qp.get("code"), qp.get("state"), qp.get("error")
    st.query_params.clear()
    if not code:
        st.session_state["flash"] = google_drive.login_error_message(error)
    elif not google_drive.verify_state(state, secret):
        st.session_state["flash"] = messages.GOOGLE_STATE_INVALID
    else:
        try:
            st.session_state["google"] = google_drive.exchange_code(code, cid, secret, redirect)
            st.session_state.pop("sheet_cache", None)
            st.session_state["flash"] = messages.GOOGLE_LOGIN_DONE
        except google_drive.GoogleError as e:
            st.session_state["flash"] = str(e)
    st.rerun()


def _current_login(settings):
    """지금 쓸 구글 로그인({'access_token','email'}) 또는 None."""
    if settings == NATIVE:
        login = native_auth.current_login()
        # 만료된 토큰이 쿠키에 남아 있으면 로그인 안 된 것으로 보고 다시 로그인하게 한다
        if login and login["access_token"] == st.session_state.get("expired_token"):
            return None
        return login
    return st.session_state.get("google")


def _forget_login():
    """토큰이 만료·취소되었을 때: 세션 로그인과 시트 캐시를 지운다(내장 로그인은 그 토큰을 만료로 표시)."""
    login = st.session_state.pop("google", None) or native_auth.current_login()
    if login:
        st.session_state["expired_token"] = login["access_token"]
    st.session_state.pop("sheet_cache", None)


def _open_storage():
    """(저장소 또는 None, 안내 문구 또는 None, 구글 설정 또는 None).
    secrets의 [auth]가 있으면 내장 로그인(같은 창), 구글 설정(GOOGLE_CLIENT_ID·SECRET)이 있으면 기존 로그인,
    둘 다 없으면 이 PC의 SQLite."""
    settings = NATIVE if native_auth.enabled() else google_drive.oauth_settings()
    if settings is None:
        store = storage.LocalStorage()
        ok = repository.init_db(store.prepare()).ok
        return (store, None, None) if ok else (None, messages.STORE_UNAVAILABLE, None)
    if settings != NATIVE:
        _handle_google_redirect(settings)
    login = _current_login(settings)
    if not login:
        return None, messages.GOOGLE_LOGIN_NEEDED, settings
    cache = st.session_state.setdefault("sheet_cache", {})
    if cache.get("owner") != login.get("email"):  # 다른 계정으로 바뀌었으면 이전 사람 기록을 버린다
        storage.SheetStorage(None, cache).reset()
        cache.clear()
        cache["owner"] = login.get("email")
    store = storage.SheetStorage(google_drive.SheetClient(login["access_token"]), cache)
    try:
        store.prepare()
        return store, None, settings
    except google_drive.AuthExpired as e:
        _forget_login()
        return None, str(e), settings
    except google_drive.GoogleError as e:
        return None, str(e), settings


def _render_google_account(settings, box):
    """사이드바 맨 아래 계정 카드(box): 로그인 상태와 로그인·로그아웃 버튼."""
    login = _current_login(settings)
    if login:
        email = login.get("email") or "구글 계정"
        row = box.container(horizontal=True, wrap=False, vertical_alignment="center", gap="small")
        row.html(f'<div class="avatar">{html.escape(email[:1].upper())}</div>', width="content")
        row.caption(messages.GOOGLE_LOGGED_IN_AS.format(email=email))
        if box.button(messages.GOOGLE_LOGOUT_BUTTON, key="google-logout", icon=":material/logout:", use_container_width=True):
            st.session_state.pop("google", None)
            st.session_state.pop("sheet_cache", None)
            if settings == NATIVE:
                native_auth.logout()
            st.rerun()
    elif settings == NATIVE:
        if google_drive.is_in_app_browser(_request_headers().get("user-agent")):
            box.warning(messages.GOOGLE_IN_APP_BROWSER)
        if box.button(messages.GOOGLE_LOGIN_BUTTON, key="google-login", type="primary", icon="🔑",
                      help=messages.GOOGLE_LOGIN_HELP, use_container_width=True):
            native_auth.login()
        box.caption(messages.GOOGLE_LOGIN_HINT_SAME_WINDOW)
    else:
        cid, secret, redirect = settings
        headers = _request_headers()
        if google_drive.is_in_app_browser(headers.get("user-agent")):
            box.warning(messages.GOOGLE_IN_APP_BROWSER)
        if google_drive.redirect_host_mismatch(headers.get("x-forwarded-host") or headers.get("host"), redirect):
            box.error(messages.GOOGLE_REDIRECT_MISMATCH.format(
                want=redirect, host=headers.get("x-forwarded-host") or headers.get("host")))
        box.link_button(messages.GOOGLE_LOGIN_BUTTON,
                        google_drive.auth_url(cid, redirect, google_drive.make_state(secret)),
                        type="primary", icon="🔑", use_container_width=True)
        box.caption(messages.GOOGLE_LOGIN_HINT)


def _request_headers():
    """브라우저 요청 헤더(소문자 키). 테스트·구버전 등 헤더가 없으면 빈 dict."""
    try:
        return {str(k).lower(): v for k, v in dict(st.context.headers).items()}
    except Exception:
        return {}


DEFAULT_PERIOD = messages.PERIOD_ONGOING  # 처음 화면의 기간 필터
DEFAULT_REGION = "서울"                    # 처음 화면의 지역 필터(목록에 서울이 없으면 '전체')
PAST_DEFAULT_DAYS = 90                     # '지난 전시' 기본 기간: 어제까지 90일
PANE_HEIGHT = 720  # 전시 찾기의 목록 칸·상세 칸 높이(px). 두 칸은 각자 따로 스크롤된다.
# 디자인 시안 C '다크 갤러리' (기본 색·글꼴은 .streamlit/config.toml의 [theme])
SAVE_BUTTON_COLOR = "#c9a45c"   # 금색 포인트
SAVE_BUTTON_HOVER = "#dcb96f"
SAVE_BUTTON_TEXT = "#16171b"    # 금색 버튼 위 글자는 어두운 색(대비)
ACCENT_TEXT = "#d8b46a"         # 칸 제목·상태 묶음 제목
MUTED_TEXT = "#9a9890"
CARD_LINE = "#2e2f36"
INFO_BG = "#16171b"
FILTER_CARD_BG = "#1b1c21"      # 필터 카드: 사이드바(#101114)보다 한 톤 밝게
FILTER_CARD_LINE = "#2a2b31"
FILTER_INPUT_BG = "#121317"     # 필터 카드 안 입력 칸: 카드보다 어둡게
POSTER_WIDTH = 150              # 상세 칸 포스터 폭(px)
THUMB_WIDTH = 64                # 목록 카드 썸네일 폭(px)
CLOSING_SOON_DAYS = 7           # 끝나기 7일 전부터 '마감임박' 배지
BADGE_COLORS = {  # 배지 (글자색, 배경색)
    "전시중": ("#7fd19b", "#1f3a2a"), "전시예정": ("#8fb4ff", "#1f2a44"),
    "종료": ("#9a9890", "#2a2b31"), "마감": ("#f0b35a", "#3d2f17"),
}

MY_CARD_TITLE_SIZE = "1.2rem"  # 내 전시 카드 제목: 본문 글자(1rem)의 120%
STATUS_HEADING_COLOR = ACCENT_TEXT           # 전체 탭 상태 묶음 제목 색(금색)
PANE_FONT_SIZE = "1rem"  # 목록 칸(두 번째) 글자 크기. 상세 칸(세 번째)의 장소 글자도 이 크기다
DETAIL_TITLE_SIZE = f"calc({PANE_FONT_SIZE} + 1pt)"  # 상세 칸 전시 제목: 1pt 크게
DETAIL_TEXT_SIZE = f"calc({PANE_FONT_SIZE} - 1pt)"   # 상세 칸의 제목·장소를 뺀 나머지: 1pt 작게

# 상세 칸: 전시 제목(+1pt)·장소(기준 크기)를 뺀 나머지 글자는 1pt 작게, 글꼴은 목록 칸과 같게 한다.
# 관심 저장 버튼에는 색을 넣는다. 선택자는 Streamlit key가 만드는 st-key-* 클래스 기준
# (detail-head = 제목·장소를 감싼 컨테이너).
_PAGE_CSS = f"""
<style>
.st-key-list-pane button p {{ font-size: {PANE_FONT_SIZE} !important; }}
.st-key-detail-pane p, .st-key-detail-pane li, .st-key-detail-pane a,
.st-key-detail-pane h3, .st-key-detail-pane button p {{
    font-size: {DETAIL_TEXT_SIZE} !important; font-family: inherit !important; line-height: 1.5 !important;
}}
.st-key-detail-head p {{ font-size: {PANE_FONT_SIZE} !important; }}
.st-key-detail-pane h2 {{ font-size: {DETAIL_TITLE_SIZE} !important; font-family: inherit !important; line-height: 1.5 !important; font-weight: 700 !important; padding: 0.15rem 0 0.1rem 0 !important; letter-spacing: 0 !important; }}
.st-key-detail-pane h3 {{ font-weight: 600 !important; padding: 0.6rem 0 0.1rem 0 !important; letter-spacing: 0 !important; }}
.st-key-detail-pane h2 a, .st-key-detail-pane h3 a {{ display: none !important; }}
/* 내 전시: 카드의 전시 제목은 본문의 120% */
.st-key-all-tab h3, div[class*="st-key-status-tab-"] h3 {{ font-size: {MY_CARD_TITLE_SIZE} !important; }}
/* 전체 탭: [관심]/[관람예정]/[관람완료] 묶음 제목은 금색, 묶음 사이 간격을 넓힌다 */
.st-key-all-tab div[class*="st-key-goto-"] {{ padding-top: 1.8rem; }}
.st-key-all-tab div[class*="st-key-goto-"] button {{ background: transparent !important; border: 0 !important;
    padding: 0 !important; min-height: 0 !important; }}
.st-key-all-tab div[class*="st-key-goto-"] button p {{ color: {STATUS_HEADING_COLOR} !important;
    font-size: 1.25rem !important; font-weight: 600 !important; }}
.st-key-all-tab div[class*="st-key-goto-"] button:hover p {{ color: {SAVE_BUTTON_HOVER} !important;
    text-decoration: underline; }}
/* 목록 칸·상세 칸 위의 제목 */
.pane-title {{ font-size: 1.2rem; font-weight: 700; color: {STATUS_HEADING_COLOR}; text-align: center;
               padding: 0.1rem 0 0.35rem 0.1rem; }}
div[class*="st-key-save-"] button {{
    background-color: {SAVE_BUTTON_COLOR} !important; border-color: {SAVE_BUTTON_COLOR} !important;
    color: {SAVE_BUTTON_TEXT} !important; font-weight: 600;
}}
div[class*="st-key-save-"] button p {{ color: {SAVE_BUTTON_TEXT} !important; }}
/* 금색 기본(primary) 버튼 위 글자는 어둡게 */
button[kind="primary"], button[kind="primary"] p {{ color: {SAVE_BUTTON_TEXT} !important; }}
/* 목록 카드: 제목 버튼은 글자처럼 보이게(왼쪽 정렬, 글꼴·크기는 원래대로), 고른 카드는 금색 테두리 */
.st-key-list-pane div[class*="st-key-card-"] {{ border: 1px solid {CARD_LINE}; border-radius: 10px;
    padding: 10px 12px; background: #1f2026; }}
.st-key-list-pane div[class*="st-key-card-sel-"] {{ border: 2px solid {SAVE_BUTTON_COLOR}; }}
.st-key-list-pane div[class*="st-key-pick-"] button {{ background: transparent !important; border: 0 !important;
    padding: 0 !important; min-height: 0 !important; justify-content: flex-start !important;
    text-align: left !important; }}
.st-key-list-pane div[class*="st-key-pick-"] button p {{
    text-align: left !important; line-height: 1.4 !important; }}
.st-key-list-pane div[class*="st-key-pick-"] button:hover p {{ color: {SAVE_BUTTON_COLOR} !important; }}
.st-key-list-pane img, .st-key-detail-pane img {{ border-radius: 6px; }}
.thumb-empty {{ width: {THUMB_WIDTH}px; height: 86px; border-radius: 6px;
    background: linear-gradient(160deg, #2c2a22, #1f2026); }}
.badge {{ display: inline-block; font-size: 0.74rem; border-radius: 999px; padding: 1px 9px; margin: 2px 4px 0 0;
    font-weight: 500; }}
.info-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin: 8px 0 12px 0; }}
.info-grid div {{ background: {INFO_BG}; border: 1px solid {CARD_LINE}; border-radius: 8px; padding: 8px 10px;
    font-size: {DETAIL_TEXT_SIZE}; line-height: 1.45; }}
.info-grid div.wide {{ grid-column: 1 / -1; }}
.info-grid b {{ display: block; color: {MUTED_TEXT}; font-weight: 500; font-size: 0.76rem; margin-bottom: 2px; }}
.tagline {{ color: {MUTED_TEXT}; font-size: 0.85rem; margin: -0.4rem 0 0.4rem 0; }}
div[class*="st-key-save-"] button:hover {{
    background-color: {SAVE_BUTTON_HOVER} !important; border-color: {SAVE_BUTTON_HOVER} !important;
}}
div[class*="st-key-save-"] button:disabled {{ opacity: 0.45; }}
/* 사이드바: 로고(=처음 화면 버튼)는 제목 글자처럼, 계정 카드는 맨 아래에 */
.st-key-home button {{ background: transparent !important; border: 0 !important; padding: 0 !important;
    min-height: 0 !important; justify-content: flex-start !important; }}
.st-key-home button p {{ font-size: 1.6rem !important; font-weight: 700 !important; }}
.st-key-home button:hover p {{ color: {SAVE_BUTTON_COLOR} !important; }}
[data-testid="stSidebarUserContent"] {{ min-height: 100%; display: flex; flex-direction: column; }}
[data-testid="stSidebarUserContent"] > div:first-child {{ flex: 1; display: flex; flex-direction: column; }}
[data-testid="stSidebarUserContent"] > div:first-child > div[data-testid="stVerticalBlock"] {{ flex: 1; }}
[data-testid="stSidebarUserContent"] [data-testid="stLayoutWrapper"]:has(> .st-key-account-card) {{
    margin-top: auto !important; }}
.avatar {{ width: 28px; height: 28px; border-radius: 50%; background: {SAVE_BUTTON_COLOR}; color: {SAVE_BUTTON_TEXT};
    display: grid; place-items: center; font-weight: 700; font-size: 0.8rem; }}
.st-key-account-card [data-testid="stCaptionContainer"] p {{ overflow: hidden; text-overflow: ellipsis;
    white-space: nowrap; margin: 0; }}
/* 필터 카드(시안 A): 사이드바보다 한 톤 밝은 카드 + 금색 윗줄 + 그림자, 입력 칸은 더 어둡게 */
.st-key-filter-card {{ background: {FILTER_CARD_BG} !important; border: 1px solid {FILTER_CARD_LINE} !important;
    border-top: 3px solid {SAVE_BUTTON_COLOR} !important; border-radius: 9px !important;
    box-shadow: 0 6px 18px rgba(0, 0, 0, 0.35); }}
/* 입력 칸(Streamlit 1.67: 선택 칸·날짜 칸은 react-aria [role=group], 글자 칸은 stTextInputRootElement) */
.st-key-filter-card [role="group"], .st-key-filter-card [data-testid="stTextInputRootElement"] {{
    background-color: {FILTER_INPUT_BG} !important; border-color: {FILTER_CARD_LINE} !important; }}
.filter-title {{ font-size: 0.78rem; font-weight: 700; color: {ACCENT_TEXT}; letter-spacing: 0.08em; }}
.st-key-reset-filters button {{ background: transparent !important; border: 0 !important; padding: 0 !important;
    min-height: 0 !important; }}
.st-key-reset-filters button p {{ color: {ACCENT_TEXT} !important; font-size: 0.8rem !important; }}
/* 본문 맨 위 메뉴: 라디오를 탭 줄처럼 */
.st-key-top-nav {{ border-bottom: 1px solid {CARD_LINE}; padding-bottom: 0.4rem; }}
.st-key-top-nav [role="radiogroup"] {{ gap: 0.3rem !important; }}
.st-key-top-nav [data-testid="stRadioOption"] {{ padding: 0.35rem 0.9rem; border-radius: 8px; margin: 0 !important;
    cursor: pointer; }}
.st-key-top-nav [data-testid="stRadioOption"] > div > div:first-child {{ display: none !important; }}
.st-key-top-nav [data-testid="stRadioOption"]:hover {{ background: #24252b; }}
.st-key-top-nav [data-testid="stRadioOption"][data-selected="true"] {{ background: #2a2618;
    box-shadow: inset 0 -2px 0 {SAVE_BUTTON_COLOR}; }}
.st-key-top-nav [data-testid="stRadioOption"][data-selected="true"] p {{ color: {ACCENT_TEXT} !important;
    font-weight: 600; }}
.st-key-top-nav [role="radiogroup"] > div:nth-child(1) p::before {{ content: "🔍 "; }}
.st-key-top-nav [role="radiogroup"] > div:nth-child(2) p::before {{ content: "📒 "; }}
.st-key-top-nav [role="radiogroup"] > div:nth-child(3) p::before {{ content: "💬 "; }}
/* 휴대폰(좁은 화면): 두 칸이 세로로 쌓이므로 목록은 화면 절반 높이로, 상세는 내용 길이만큼 */
@media (max-width: 640px) {{
    .st-key-list-pane {{ height: auto !important; max-height: 55vh !important; }}
    .st-key-detail-pane {{ height: auto !important; max-height: none !important; }}
    .info-grid {{ grid-template-columns: 1fr; }}
    .st-key-detail-hero {{ flex-wrap: wrap !important; }}
}}
</style>
"""


def _region_text(region, districts=None):
    """'서울' / '서울(종로구·중구)' / '서울(종로구 외 2)' / '서울·부산' / '전체'."""
    regions = [region] if isinstance(region, str) else list(region or [])
    regions = [r for r in regions if r and r != messages.REGION_ALL]
    if not regions:
        return messages.REGION_ALL
    parts = []
    for r in regions:
        ds = (districts or {}).get(r) or []
        if not ds:
            parts.append(r)
        elif len(ds) <= 2:
            parts.append(f"{r}({'·'.join(ds)})")
        else:
            parts.append(f"{r}({ds[0]} 외 {len(ds) - 1})")
    return "·".join(parts)


def list_pane_title(region, period, districts=None, past_range=None):
    """목록 칸 제목. 예: '서울 - 전시중인 목록', '서울(종로구)·부산 - 전시예정인 목록',
    '전체 - 지난 전시 목록 (2026-08-01 ~ 2026-11-11)', '부산 - 전체 기간 목록'."""
    where = _region_text(region, districts)
    if period == messages.PERIOD_PAST:
        span = f" ({past_range[0]} ~ {past_range[1]})" if past_range else ""
        return f"{where} - {messages.PERIOD_PAST} 목록{span}"
    period_text = {messages.PERIOD_ONGOING: "전시중인", messages.PERIOD_UPCOMING: "전시예정인"}.get(period, "전체 기간")
    return f"{where} - {period_text} 목록"


_FILTER_KEYS = ("page", "period", "regions", "keyword", "art-only", "sort", "past-range", "selected_id")


def _go_home():
    """처음 화면으로: 페이지·필터·선택을 기본값으로 되돌린다(로그인·대화 기록은 유지)."""
    # 화면에 보이는 위젯은 키를 지우기만 하면 브라우저 쪽 값이 남을 수 있어, 기본값을 직접 넣는다.
    widget_defaults = {"page": messages.PAGE_FIND, "period": DEFAULT_PERIOD, "regions": [DEFAULT_REGION],
                       "keyword": "", "art-only": False,
                       "sort": messages.SORT_DEFAULT}
    for k in list(st.session_state.keys()):
        if str(k).startswith("districts-"):
            st.session_state[k] = []
        elif k in _FILTER_KEYS and k not in widget_defaults:
            del st.session_state[k]
    for k, v in widget_defaults.items():
        st.session_state[k] = v


def _pick(exhibition_id):
    st.session_state["selected_id"] = exhibition_id


def _load_past(start, end):
    """지난 전시(기간 조회 API). 같은 기간은 세션 동안 다시 부르지 않는다. (목록 또는 None, 잘림 여부)"""
    cache = st.session_state.setdefault("past_cache", {})
    key = (start.isoformat(), end.isoformat())
    if key not in cache:
        try:
            cache[key] = culture_api.fetch_exhibitions_between(start, end)
        except culture_api.CultureApiError:
            cache[key] = (None, False)
    return cache[key]


def _period_tag(e, today):
    t = today.isoformat()
    if e.end_date < t:
        return messages.PERIOD_ENDED_TAG
    return messages.PERIOD_ONGOING if e.start_date <= t else messages.PERIOD_UPCOMING


def _badge(text, kind):
    fg, bg = BADGE_COLORS[kind]
    return f'<span class="badge" style="color:{fg};background:{bg}">{html.escape(text)}</span>'


def badges_html(e, today):
    """상태 배지(전시중/전시예정/종료)와, 끝나기 7일 안이면 'D-n 마감임박' 배지."""
    tag = _period_tag(e, today)
    out = _badge(tag, tag)
    if tag == messages.PERIOD_ONGOING:
        end = _parse_iso(e.end_date)
        left = (end - today).days if end else None
        if left is not None and 0 <= left <= CLOSING_SOON_DAYS:
            out += _badge(messages.CLOSING_SOON.format(days=left), "마감")
    return out


MAP_ZOOM = 15
MAP_HEIGHT = 260


def _render_map(place, info):
    """위치: '📍 장소 · 주소' 한 줄, 지명이 보이는 지도에 금색 핀(마우스를 올리면 장소·주소), 카카오맵 보기·길찾기 링크.
    (핀 위 글자(TextLayer)는 Streamlit 지도에서 그려지지 않아 쓰지 않는다)"""
    lat, lon = info["lat"], info["lon"]
    name = place or messages.MAP_UNKNOWN_PLACE
    st.subheader(messages.MAP_HEADING)
    st.caption(" · ".join(x for x in ("📍 " + name, info.get("address")) if x))
    import pydeck as pdk
    point = [{"lat": lat, "lon": lon, "name": name, "address": info.get("address") or ""}]
    layers = [  # 바깥 옅은 금색 원 + 안쪽 진한 금색 핀: 지도 위에서 잘 보이게
        pdk.Layer("ScatterplotLayer", point, get_position="[lon, lat]", get_radius=60, radius_min_pixels=16,
                  radius_max_pixels=28, get_fill_color=[201, 164, 92, 70]),
        pdk.Layer("ScatterplotLayer", point, get_position="[lon, lat]", get_radius=12, radius_min_pixels=7,
                  radius_max_pixels=12, get_fill_color=[201, 164, 92, 255], stroked=True,
                  get_line_color=[22, 23, 27], line_width_min_pixels=2, pickable=True),
    ]
    st.pydeck_chart(pdk.Deck(layers=layers, map_style="road", tooltip={"text": "{name}\n{address}"},
                             initial_view_state=pdk.ViewState(latitude=lat, longitude=lon, zoom=MAP_ZOOM)),
                    height=MAP_HEIGHT)
    view, route = search_api.kakao_map_links(name, lat, lon)
    st.markdown(f"[🗺 {messages.MAP_OPEN_KAKAO}]({view}) · [🧭 {messages.MAP_DIRECTIONS}]({route})")


def _render_detail_info(info, place=""):
    """요금·주소·문의(아이콘 칸), 안내 링크와 지도(좌표가 있을 때)."""
    if not info:
        st.caption(messages.DETAIL_NO_INFO)
        return
    cells = [("💰 " + messages.DETAIL_PRICE, info.get("price"), ""),
             ("☎ " + messages.DETAIL_PHONE, info.get("phone"), ""),
             ("🏛 " + messages.DETAIL_ADDRESS, info.get("address"), "wide")]
    st.markdown('<div class="info-grid">' + "".join(
        f'<div class="{cls}"><b>{html.escape(label)}</b>{html.escape(value or messages.DETAIL_INFO_MISSING)}</div>'
        for label, value, cls in cells) + "</div>", unsafe_allow_html=True)
    link = info.get("url") or info.get("place_url")
    if link:
        st.markdown(f"[{messages.DETAIL_LINK}]({link})")
    if info.get("lat") is not None and info.get("lon") is not None:
        _render_map(place, info)


def _parse_iso(value):
    from datetime import date
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _default_actual_date(planned, today):
    """실제 관람일 기본값: 관람예정일이 오늘 이전이면 그날, 아니면(미래·없음) 오늘."""
    d = _parse_iso(planned)
    return d if d and d <= today else today


def _render_interest(db_path, r, today, opened=True):
    eid = r["exhibition_id"]
    c1, c2 = st.columns([2, 1], vertical_alignment="bottom")
    with c1:
        picked = st.date_input(messages.PLANNED_DATE_LABEL, value=today, key=f"plan-date-{eid}",
                               format="YYYY-MM-DD")
    with c2:
        if st.button(messages.PLAN_BUTTON, key=f"plan-{eid}", type="primary"):
            _flash(repository.plan(db_path, eid, picked.isoformat() if picked else "", today=today),
                   messages.PLANNED_DONE)


def _render_planned(db_path, r, today, opened=True):
    eid = r["exhibition_id"]
    current = _parse_iso(r["planned_visit_date"]) or today
    c1, c2 = st.columns([2, 1], vertical_alignment="bottom")
    with c1:
        picked = st.date_input(messages.PLANNED_DATE_LABEL, value=current, key=f"change-date-{eid}",
                               format="YYYY-MM-DD")
    with c2:
        if st.button(messages.CHANGE_DATE_BUTTON, key=f"change-{eid}"):
            _flash(repository.change_planned_date(db_path, eid, picked.isoformat() if picked else "",
                                                  today=today),
                   messages.DATE_CHANGED_DONE)
    c3, c4 = st.columns([2, 1], vertical_alignment="bottom")
    with c3:
        actual = st.date_input(messages.ACTUAL_DATE_LABEL,
                               value=_default_actual_date(r["planned_visit_date"], today),
                               max_value=today, key=f"actual-date-{eid}", format="YYYY-MM-DD")
    with c4:
        if st.button(messages.COMPLETE_BUTTON, key=f"done-{eid}", type="primary"):
            _flash(repository.complete(db_path, eid, actual.isoformat() if actual else "", today=today),
                   messages.COMPLETED_DONE)
    st.caption(messages.COMPLETE_NOTE)


def _set_state(key, value):
    st.session_state[key] = value


# ---------- 삭제 공통 규칙: 모든 삭제는 '삭제 버튼 → 경고 문구 + [삭제]/[취소]' 두 단계로 한다 ----------
# 버튼 key가 K이면: 묻는 중 표시 K-ask, 확인 버튼 K-yes, 취소 버튼 K-no.
# 실제 삭제 함수는 버튼 콜백에서 실행되므로 st.rerun 대신 _remember_result로 결과를 남긴다.

def _ask_delete_button(where, label, key, icon=":material/delete:"):
    """첫 단계: 누르면 지우지 않고 '묻는 중' 상태만 켠다."""
    where.button(label, key=key, icon=icon, on_click=_set_state, args=(f"{key}-ask", True))


def _asking(key):
    return bool(st.session_state.get(f"{key}-ask"))


def _confirm_delete(key, message, on_confirm, args=()):
    """둘째 단계: 경고 문구와 [삭제]/[취소]. [삭제]를 눌러야 on_confirm(*args)가 실행된다."""
    st.warning(message, icon="⚠️")
    c1, c2 = st.columns(2)
    c1.button(messages.DELETE_YES, key=f"{key}-yes", type="primary", icon=":material/delete:",
              on_click=_run_confirmed, args=(key, on_confirm, args))
    c2.button(messages.DELETE_NO, key=f"{key}-no", on_click=_set_state, args=(f"{key}-ask", False))


def _run_confirmed(key, on_confirm, args):
    st.session_state[f"{key}-ask"] = False
    on_confirm(*args)


def _delete_review(db_path, eid, today):
    """삭제 확인 후: 관람평을 지우고 입력란(별점·글)도 비운다(콜백이라 위젯보다 먼저 값을 바꿀 수 있다)."""
    result = repository.delete_review(db_path, eid, today=today)
    if result.ok:
        st.session_state[f"review-text-{eid}"] = ""
        st.session_state[f"rating-{eid}"] = 5
    _remember_result(result, messages.REVIEW_DELETED_DONE)


def _render_done(db_path, r, today, opened=True):
    eid = r["exhibition_id"]
    c1, c2 = st.columns([2, 1], vertical_alignment="bottom")
    with c1:
        actual = st.date_input(messages.ACTUAL_DATE_LABEL,
                               value=_parse_iso(r["actual_visit_date"])
                               or _default_actual_date(r["planned_visit_date"], today),
                               max_value=today, key=f"actual-change-date-{eid}", format="YYYY-MM-DD")
    with c2:
        if st.button(messages.CHANGE_ACTUAL_DATE_BUTTON, key=f"actual-change-{eid}"):
            _flash(repository.change_actual_date(db_path, eid, actual.isoformat() if actual else "",
                                                 today=today),
                   messages.ACTUAL_DATE_CHANGED_DONE)
    # 관람평: 저장된 별점·글을 입력란에 채워 한 곳에서 보고 고친다(따로 보여 주지 않는다)
    has_review = r["review_rating"] is not None
    rating_key, text_key, del_key = f"rating-{eid}", f"review-text-{eid}", f"review-del-{eid}"
    # 입력란 값은 세션 값으로만 정한다(삭제 후 입력란을 비울 때 경고가 나지 않게)
    st.session_state.setdefault(rating_key, r["review_rating"] if has_review else 5)
    st.session_state.setdefault(text_key, r["review_text"] or "")
    st.markdown(f"**{messages.REVIEW_HEADING}**")
    if not has_review:
        st.caption(messages.NO_REVIEW)
    rating = st.radio(messages.RATING_LABEL, [1, 2, 3, 4, 5], format_func=lambda n: "★" * n, horizontal=True,
                      key=rating_key)
    text = st.text_area(messages.REVIEW_TEXT_LABEL, max_chars=1000, key=text_key)
    if _asking(del_key):  # 삭제 버튼을 누른 뒤: 한 번 더 묻는다
        _confirm_delete(del_key, messages.REVIEW_DELETE_CONFIRM, _delete_review, (db_path, eid, today))
    else:
        c1, c2 = st.columns(2)
        with c1:
            if st.button(messages.REVIEW_SAVE_BUTTON, key=f"review-{eid}", type="primary"):
                _flash(repository.write_review(db_path, eid, rating, text, today=today),
                       messages.REVIEW_SAVED_DONE)
        if has_review:
            _ask_delete_button(c2, messages.REVIEW_DELETE_BUTTON, del_key)
    if opened:  # 사진은 펼쳤을 때만 불러온다(기록이 많아도 처음 화면이 느려지지 않게)
        _render_photos(db_path, r, editable=True)


PHOTO_WIDTH = 150        # 관람완료 탭의 사진 폭(px)
PHOTO_THUMB_WIDTH = 96   # 전체 탭의 작은 사진 폭(px)


def _photo_bytes(photo_id):
    """저장소에서 사진을 읽는다. 실패하면 None(화면에는 '불러오지 못했습니다')."""
    try:
        return _STORE.load_photo(photo_id)
    except google_drive.AuthExpired:
        _forget_login()
    except Exception:
        pass
    return None


def _render_photos(db_path, r, editable):
    """관람 사진: 작은 사진 줄(마우스를 올리면 크게 보기). editable이면 사진별 삭제와 올리기 칸."""
    eid = r["exhibition_id"]
    ids = photos.parse_ids(r.get("photo_ids"))
    if not ids and not editable:
        return
    if editable:
        st.markdown(f"**{messages.PHOTO_HEADING.format(count=len(ids), limit=photos.MAX_PHOTOS)}**")
        st.caption(messages.PHOTO_NOTE if getattr(_STORE, "kind", "") == "google" else messages.PHOTO_NOTE_LOCAL)
    if ids:
        row = st.container(horizontal=True, gap="small", key=f"photos-{'edit' if editable else 'view'}-{eid}")
        for pid in ids:
            with row.container(width="content"):
                data = _photo_bytes(pid)
                if data:
                    st.image(data, width=PHOTO_WIDTH if editable else PHOTO_THUMB_WIDTH)
                else:
                    st.caption(messages.PHOTO_LOAD_FAILED)
                if editable:
                    _ask_delete_button(st, messages.PHOTO_DELETE_BUTTON, f"photo-del-{eid}-{pid}")
        # 사진 칸은 좁아서, 삭제 확인은 사진 줄 아래에 넓게 보여 준다
        for pid in ids if editable else []:
            if _asking(f"photo-del-{eid}-{pid}"):
                _confirm_delete(f"photo-del-{eid}-{pid}", messages.PHOTO_DELETE_CONFIRM, _delete_photo,
                                (db_path, eid, pid))
    if editable and len(ids) < photos.MAX_PHOTOS:
        turn = st.session_state.get(f"photo-turn-{eid}", 0)  # 올린 뒤 고르기 칸을 비우려고 key를 바꾼다
        picked = st.file_uploader(messages.PHOTO_UPLOAD_LABEL, type=photos.ACCEPTED_TYPES,
                                  key=f"photo-up-{eid}-{turn}")
        if picked is not None and st.button(messages.PHOTO_UPLOAD_BUTTON, key=f"photo-add-{eid}", type="primary",
                                            icon=":material/upload:"):
            _add_photo(db_path, eid, picked)


def _add_photo(db_path, eid, picked):
    """사진을 줄여 저장소에 올리고 기록에 붙인다. 기록에 못 붙이면 올린 사진을 지운다."""
    try:
        data = photos.prepare_image(picked.getvalue())
        photo_id = _STORE.save_photo(f"{eid}-{picked.name}", data, photos.MIME)
    except photos.PhotoError as e:
        st.session_state["flash"] = str(e)
        st.rerun()
    except google_drive.AuthExpired as e:
        _forget_login()
        st.session_state["flash"] = str(e)
        st.rerun()
    except Exception:
        st.session_state["flash"] = messages.PHOTO_UPLOAD_FAILED
        st.rerun()
    result = repository.add_photo(db_path, eid, photo_id)
    if result.ok:
        st.session_state[f"photo-turn-{eid}"] = st.session_state.get(f"photo-turn-{eid}", 0) + 1
    else:
        _forget_photo(photo_id)
    _flash(result, messages.PHOTO_ADDED_DONE)


def _forget_photo(photo_id):
    """저장소에서 사진 파일을 지운다(실패해도 기록에는 영향 없음)."""
    try:
        _STORE.delete_photo(photo_id)
    except Exception:
        pass


def _delete_photo(db_path, eid, photo_id):
    """사진 삭제(확인 버튼 콜백에서 실행)."""
    result = repository.remove_photo(db_path, eid, photo_id)
    if result.ok:
        _forget_photo(photo_id)
    _remember_result(result, messages.PHOTO_DELETED_DONE)


def _delete_record(db_path, eid):
    """전시 기록을 지우면 그 기록의 사진 파일도 지운다(확인 버튼 콜백에서 실행)."""
    ids = repository.photo_ids_of(db_path, eid)
    result = repository.delete(db_path, eid)
    if result.ok:
        for pid in ids:
            _forget_photo(pid)
        st.session_state.pop(f"rec-open-{eid}", None)
    _remember_result(result, messages.RECORD_DELETED_DONE)


_STATUS_CONTROLS = {
    repository.STATUS_INTEREST: _render_interest,
    repository.STATUS_PLANNED: _render_planned,
    repository.STATUS_DONE: _render_done,
}


def _date_line(r):
    parts = [f"{messages.PLANNED_DATE_LABEL} {r['planned_visit_date']}" if r["planned_visit_date"] else "",
             f"{messages.ACTUAL_DATE_LABEL} {r['actual_visit_date']}" if r.get("actual_visit_date") else ""]
    return " · ".join(p for p in parts if p)


MY_TABS_KEY = "my-tab"  # 내 전시 탭의 선택(전체/관심/관람예정/관람완료). 값을 바꾸면 그 탭이 열린다.


def _open_status_tab(status):
    """전체 탭의 묶음 제목을 누르면 그 상태의 탭으로 넘어간다."""
    st.session_state[MY_TABS_KEY] = messages.TAB_LABELS[repository.STATUSES.index(status)]


def _render_all(db_path):
    """전체 탭: [관심] → [관람예정] → [관람완료] 제목 아래에 상태별 목록을 모아 본다.
    묶음 제목을 누르면 그 상태의 탭으로 넘어간다(전시별 조작 버튼은 두지 않는다:
    같은 전시의 위젯이 상태 탭과 겹쳐 두 번 생기지 않도록)."""
    if not repository.count(db_path):
        st.write(messages.EMPTY_TAB)
        return
    st.caption(messages.ALL_TAB_NOTE)
    for status in repository.STATUSES:
        rows = repository.list_by_status(db_path, status)
        st.button(messages.STATUS_GROUP_TITLE.format(status=status, count=len(rows)), key=f"goto-{status}",
                  on_click=_open_status_tab, args=(status,), help=messages.STATUS_GROUP_HELP.format(status=status))
        if not rows:
            st.caption(messages.EMPTY_TAB)
        for r in rows:
            _render_all_card(r)


def _render_all_card(r):
    with st.container(border=True):
        st.subheader(r["title"])
        st.caption(" · ".join(x for x in (r["place"], r["region"],
                                          f"{r['start_date']} ~ {r['end_date']}") if x))
        if _date_line(r):
            st.caption(_date_line(r))
        if r["review_rating"] is not None:
            st.write("★" * r["review_rating"] + "☆" * (5 - r["review_rating"]))
            st.write(r["review_text"])
        _render_photos(None, r, editable=False)


_MD_SPECIAL = str.maketrans({c: "\\" + c for c in "\\`*_[]<>#|~$"})


def _remember_open(eid):
    """펼침 상자를 열고 닫을 때: 그 상태를 따로 기억한다(제목이 바뀌어 상자가 새로 만들어져도 유지)."""
    st.session_state[f"rec-open-{eid}"] = bool(st.session_state.get(f"rec-{eid}"))


def record_label(r):
    """상태 탭의 한 줄 목록 제목. 예: '돌과 숨 · 관람일 2026-11-10 · ★★★★★ · 📷 2'.
    펼침 상자 제목은 마크다운으로 그려지므로 전시 제목의 특수 문자는 글자 그대로 보이게 한다."""
    title = str(r["title"]).translate(_MD_SPECIAL)
    if r["status"] == repository.STATUS_PLANNED:
        return messages.RECORD_LABEL_PLANNED.format(title=title, planned=r["planned_visit_date"] or "-")
    if r["status"] == repository.STATUS_DONE:
        rating = r.get("review_rating")
        n = len(photos.parse_ids(r.get("photo_ids")))
        return messages.RECORD_LABEL_DONE.format(
            title=title, actual=r.get("actual_visit_date") or "-",
            stars=f" · {'★' * rating}{'☆' * (5 - rating)}" if rating else "",
            photos=f" · 📷 {n}" if n else "")
    return messages.RECORD_LABEL_INTEREST.format(title=title, place=str(r["place"]).translate(_MD_SPECIAL),
                                                 end_date=r["end_date"])


def _render_my(db_path, today):
    if st.session_state.get("flash"):
        st.write(st.session_state.pop("flash"))
    tabs = st.tabs([messages.TAB_ALL, *messages.TAB_LABELS], key=MY_TABS_KEY, on_change="rerun")
    with tabs[0], st.container(key="all-tab"):
        _render_all(db_path)
    for i, (tab, status) in enumerate(zip(tabs[1:], repository.STATUSES, strict=True)):
        with tab, st.container(key=f"status-tab-{i}"):
            rows = repository.list_by_status(db_path, status)
            if not rows:
                st.write(messages.EMPTY_TAB)
            else:
                st.caption(messages.RECORD_LIST_NOTE)
            for r in rows:
                # 처음에는 한 줄 목록만, 누르면 펼쳐진다. 목록 줄 제목(별점·사진 수)이 바뀌면 Streamlit이 상자를
                # 새로 만들어 접어 버리므로, 열림 상태를 따로 기억해 두었다가 그대로 펼쳐 둔다.
                eid = r["exhibition_id"]
                box = st.expander(record_label(r), expanded=bool(st.session_state.get(f"rec-open-{eid}")),
                                  key=f"rec-{eid}", on_change=_remember_open, args=(eid,))
                with box:
                    st.caption(" · ".join(x for x in (r["place"], r["region"],
                                                      f"{r['start_date']} ~ {r['end_date']}") if x))
                    if status == repository.STATUS_DONE:
                        dates = [f"{messages.PLANNED_DATE_LABEL} {r['planned_visit_date']}"
                                 if r["planned_visit_date"] else "",
                                 f"{messages.ACTUAL_DATE_LABEL} {r['actual_visit_date']}"
                                 if r["actual_visit_date"] else ""]
                        if any(dates):
                            st.caption(" · ".join(d for d in dates if d))
                    _STATUS_CONTROLS[status](db_path, r, today, opened=bool(box.open))
                    if _asking(f"del-{eid}"):
                        _confirm_delete(f"del-{eid}", messages.RECORD_DELETE_CONFIRM.format(title=r["title"]),
                                        _delete_record, (db_path, eid))
                    else:
                        _ask_delete_button(st, messages.DELETE_RECORD_BUTTON, f"del-{eid}")


def _render_assistant():
    """AI 도우미: 질문 → 에이전트(src/agent.py) → 답변 + 근거 문서 + 처리 과정."""
    st.caption(messages.ASSISTANT_INTRO)
    if not llm_status.available():
        st.info(messages.AI_UNAVAILABLE, icon="⚠️")
    history = st.session_state.setdefault("chat", [])
    for turn in history:
        with st.chat_message(turn["role"]):
            st.markdown(turn["text"])
            if turn.get("contexts"):
                with st.expander(f"{messages.ASSISTANT_SOURCES} ({len(turn['contexts'])})"):
                    for c in turn["contexts"]:
                        st.caption(f"{c['doc_id']}")
                        st.text(c["text"][:400])
            if turn.get("trace"):
                with st.expander(messages.ASSISTANT_TRACE):
                    st.json(turn["trace"], expanded=False)
    question = st.chat_input(messages.ASSISTANT_PLACEHOLDER, key="assistant-input")
    if question:
        import agent  # 무거운 의존성(LangGraph)은 이 화면에서만 불러온다
        history.append({"role": "user", "text": question})
        with st.spinner("답변을 만드는 중…"):
            try:
                r = agent.run(question)
                history.append({"role": "assistant", "text": r["answer"], "contexts": r["contexts"],
                                "trace": r["trace"]})
            except Exception:
                history.append({"role": "assistant", "text": agent.FALLBACK_ANSWER})
        st.rerun()


def main():
    load_dotenv()
    config.install_secret_redaction()
    st.set_page_config(page_title=messages.APP_TITLE, layout="wide")
    st.html(_PAGE_CSS)
    today = config.today_kst()
    exhibitions = _load_exhibitions()
    base = filters.base_set(exhibitions or [], today)

    global _STORE
    _STORE, store_message, gsettings = _open_storage()
    db_ok = _STORE is not None
    db_path = _STORE.prepare() if db_ok else None
    my_label = (messages.MY_LABEL_FORMAT.format(count=repository.count(db_path)) if db_ok
                else messages.PAGE_MY)

    # 사이드바: 로고(누르면 처음 화면) · 소개 · [필터 카드: 전시 찾기에서만] · … · [계정 카드: 맨 아래]
    st.sidebar.button("🎨 " + messages.APP_TITLE, key="home", on_click=_go_home, help=messages.HOME_BUTTON)
    st.sidebar.html(f'<div class="tagline">{html.escape(messages.APP_TAGLINE)}</div>')
    filter_slot = st.sidebar.container()
    if gsettings:
        _render_google_account(gsettings, st.sidebar.container(border=True, key="account-card"))
    # 본문 맨 위: 페이지 메뉴(탭 줄)
    with st.container(key="top-nav"):
        page = st.radio("페이지", [messages.PAGE_FIND, messages.PAGE_MY, messages.PAGE_ASSISTANT],
                        format_func=lambda p: my_label if p == messages.PAGE_MY else p,
                        horizontal=True, label_visibility="collapsed", key="page")
    if page == messages.PAGE_ASSISTANT:
        _render_assistant()
        return
    if page != messages.PAGE_FIND:
        if db_ok:
            _render_my(db_path, today)
        else:
            if st.session_state.get("flash"):
                st.write(st.session_state.pop("flash"))
            st.write(store_message)
        return
    period_options = [messages.PERIOD_ALL, messages.PERIOD_ONGOING, messages.PERIOD_UPCOMING, messages.PERIOD_PAST]
    card = filter_slot.container(border=True, key="filter-card")
    head = card.container(horizontal=True, vertical_alignment="center", horizontal_alignment="distribute")
    head.html(f'<div class="filter-title">{html.escape(messages.FILTER_CARD_TITLE)}</div>')
    head.button(messages.FILTER_RESET_BUTTON, key="reset-filters", icon=":material/restart_alt:", on_click=_go_home)
    period_col, sort_col = card.columns(2)
    # 기본값은 세션 값으로만 정한다(처음 화면 버튼이 세션 값을 바꿀 때 경고가 나지 않게).
    st.session_state.setdefault("period", DEFAULT_PERIOD)
    period = period_col.selectbox(messages.FILTER_PERIOD_LABEL, period_options, key="period")
    st.session_state.setdefault("sort", messages.SORT_DEFAULT)
    order = sort_col.selectbox(messages.FILTER_SORT_LABEL, messages.SORT_OPTIONS, key="sort")
    past_range, past_note = None, None
    if period == messages.PERIOD_PAST:
        rng = card.date_input(messages.FILTER_PAST_RANGE_LABEL,
                                    value=(today - timedelta(days=PAST_DEFAULT_DAYS), today - timedelta(days=1)),
                                    max_value=today - timedelta(days=1), key="past-range", format="YYYY-MM-DD")
        if isinstance(rng, (list, tuple)) and len(rng) == 2:
            past_range = (rng[0], rng[1])
            past, truncated = _load_past(*past_range)
            exhibitions = past
            base = [e for e in (past or []) if e.end_date < today.isoformat()]
            past_note = messages.PAST_TRUNCATED if truncated else None
        else:
            base, past_note = [], messages.PAST_RANGE_INCOMPLETE
    region_options = [r for r in filters.region_options(base) if r != messages.REGION_ALL]
    st.session_state.setdefault("regions", [DEFAULT_REGION])
    # 목록에 없는 지역(예: 기본값 '서울'이 목록에 없을 때)은 뺀다
    st.session_state["regions"] = [r for r in st.session_state["regions"] if r in region_options]
    regions = card.multiselect(messages.FILTER_REGION_LABEL, region_options,
                                     placeholder=messages.FILTER_REGION_PLACEHOLDER, key="regions")
    districts = {}
    if DEFAULT_REGION in regions:
        d_key = f"districts-{DEFAULT_REGION}"
        d_options = filters.district_options(base, DEFAULT_REGION)
        if d_key in st.session_state:
            st.session_state[d_key] = [d for d in st.session_state[d_key] if d in d_options]
        districts[DEFAULT_REGION] = card.multiselect(
            messages.FILTER_DISTRICT_LABEL, d_options, placeholder=messages.FILTER_DISTRICT_PLACEHOLDER, key=d_key)
    keyword = card.text_input(messages.FILTER_KEYWORD_LABEL, key="keyword")
    art_only = card.checkbox(messages.FILTER_ART_ONLY_LABEL, key="art-only")

    shown = filters.filter_exhibitions(base, today, messages.PERIOD_ALL if period == messages.PERIOD_PAST else period,
                                       regions, keyword, art_only=art_only, districts=districts)
    shown = filters.sort_exhibitions(shown, order)
    selected_id = st.session_state.get("selected_id")
    selected = next((e for e in shown if e.exhibition_id == selected_id), None)

    if not db_ok:
        st.write(store_message)
    if st.session_state.get("flash"):
        st.write(st.session_state.pop("flash"))
    left_col, right_col = st.columns(2)
    # 칸 제목은 스크롤 영역 밖(위)에 두어 항상 보이게 한다
    left_col.html(f'<div class="pane-title">{html.escape(list_pane_title(regions, period, districts, past_range))}</div>')
    right_col.html(f'<div class="pane-title">{html.escape(messages.DETAIL_PANE_TITLE)}</div>')
    # 두 칸을 고정 높이 컨테이너로 감싸 각자 스크롤되게 한다(목록을 내려도 상세는 제자리).
    left = left_col.container(height=PANE_HEIGHT, key="list-pane")
    right = right_col.container(height=PANE_HEIGHT, key="detail-pane")
    with left:
        if past_note:
            st.caption(past_note)
        if exhibitions is None:
            st.write(messages.CULTURE_FAILED)
            st.button(messages.RETRY_BUTTON, key="retry-load", icon="🔄", on_click=_retry_load)
        elif not shown:
            st.write(messages.NO_RESULT)
        for e in shown:
            card_key = f"card-sel-{e.exhibition_id}" if e is selected else f"card-{e.exhibition_id}"
            # 카드 = [썸네일 | 제목·장소·배지] 가로 배치(열(columns) 대신 가로 컨테이너: 칸 구조를 단순하게)
            with st.container(key=card_key, horizontal=True, wrap=False, vertical_alignment="center", gap="medium"):
                if e.thumbnail:
                    st.image(e.thumbnail, width=THUMB_WIDTH)
                else:
                    st.html('<div class="thumb-empty"></div>', width=THUMB_WIDTH)
                with st.container():
                    # 고르기는 콜백으로: 다시 그리기 전에 선택이 정해져 고른 카드 테두리가 바로 바뀐다
                    st.button(e.title, key=f"pick-{e.exhibition_id}", on_click=_pick, args=(e.exhibition_id,))
                    where = " ".join(x for x in (e.region, e.district) if x)
                    st.caption(" · ".join(x for x in (e.place, where, _period_text(e)) if x))
                    st.html(badges_html(e, today))
    with right:
        if selected is None:
            st.write(messages.SELECT_EXHIBITION)
        else:
            # 포스터가 있으면 왼쪽에 크게, 제목·장소·배지·버튼은 오른쪽
            hero = st.container(key="detail-hero", horizontal=True, wrap=False, gap="medium")
            if selected.thumbnail:
                hero.image(selected.thumbnail, width=POSTER_WIDTH)
            with hero.container():
                with st.container(key="detail-head"):  # 제목·장소: 글자 크기를 줄이지 않는 영역
                    st.header(selected.title)
                    if selected.place:
                        st.write("📍 " + selected.place)
                st.html(badges_html(selected, today))
                st.write(_period_text(selected))
                if st.button(messages.SAVE_INTEREST_BUTTON, key=f"save-{selected.exhibition_id}",
                             type="primary", icon="⭐", disabled=not db_ok):
                    _flash(repository.save(db_path, selected), messages.SAVED_DONE)
            data = _detail_data(selected)
            _render_detail_info(data.get("info"), place=selected.place)
            if data["summary"]:
                st.subheader(messages.SUMMARY_HEADING)
                st.write(data["summary"])
            search_api.render_related(st, data["related"])


main()
