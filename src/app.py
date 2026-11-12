"""미술 전시 탐색·기록 앱 화면 (streamlit run app.py). 규칙은 exhibition_app 패키지에 있다."""
import html

import streamlit as st
from dotenv import load_dotenv

from exhibition_app import (config, culture_api, filters, google_drive, messages, repository, search_api,
                            storage, summarizer)

_STORE = None  # 이번 실행의 저장소(LocalStorage 또는 SheetStorage). main()이 정한다.


def _load_exhibitions():
    """세션 중 한 번만 조회한다. 실패하면 None."""
    if "exhibitions" not in st.session_state:
        try:
            st.session_state["exhibitions"] = culture_api.fetch_exhibitions()
        except culture_api.CultureApiError:
            st.session_state["exhibitions"] = None
    return st.session_state["exhibitions"]


def _period_text(e):
    return f"{e.start_date} ~ {e.end_date}"


def _detail_data(exhibition):
    """선택이 바뀔 때만 카카오 검색·LLM을 호출하고 선택이 유지되는 동안 session_state에 캐시한다."""
    cache = st.session_state.get("detail_cache")
    if cache is None or cache["id"] != exhibition.exhibition_id:
        related = search_api.load_related(exhibition.title, place=exhibition.place)
        summary = summarizer.summarize(related["web"]["items"], related["blogs"]["items"])
        cache = {"id": exhibition.exhibition_id, "related": related, "summary": summary}
        st.session_state["detail_cache"] = cache
    return cache


def _flash(result, ok_text=None):
    """쓰기 결과를 다음 실행에서 보이도록 저장하고 다시 그린다(사이드바 건수 갱신).
    실패하면 저장 규칙이 돌려준 문구를, 성공하면 ok_text를 보여 준다.
    구글 시트를 쓰는 중이면 성공한 변경을 시트에 올리고, 올리기에 실패하면 그 문구를 보여 준다."""
    message = result.message if not result.ok else ok_text
    if result.ok and _STORE is not None:
        try:
            _STORE.after_write()
        except google_drive.AuthExpired as e:
            st.session_state.pop("google", None)
            message = str(e)
        except google_drive.GoogleError as e:
            message = str(e)
    st.session_state["flash"] = message
    st.rerun()


def _handle_google_redirect(settings):
    """구글 로그인 후 돌아온 주소(?code=…&state=… 또는 ?error=…)를 처리하고 주소를 깨끗이 한다."""
    qp = st.query_params
    if "code" not in qp and "error" not in qp:
        return
    cid, secret, redirect = settings
    code, state = qp.get("code"), qp.get("state")
    st.query_params.clear()
    if not code:
        st.session_state["flash"] = messages.GOOGLE_LOGIN_FAILED
    elif not google_drive.verify_state(state, secret):
        st.session_state["flash"] = messages.GOOGLE_STATE_INVALID
    else:
        try:
            st.session_state["google"] = google_drive.exchange_code(code, cid, secret, redirect)
            st.session_state.pop("sheet_cache", None)
        except google_drive.GoogleError as e:
            st.session_state["flash"] = str(e)
    st.rerun()


def _open_storage():
    """(저장소 또는 None, 안내 문구 또는 None, 구글 설정 또는 None).
    구글 설정(GOOGLE_CLIENT_ID·SECRET)이 없으면 이 PC의 SQLite, 있으면 로그인한 사용자의 구글 시트."""
    settings = google_drive.oauth_settings()
    if settings is None:
        store = storage.LocalStorage()
        ok = repository.init_db(store.prepare()).ok
        return (store, None, None) if ok else (None, messages.STORE_UNAVAILABLE, None)
    _handle_google_redirect(settings)
    login = st.session_state.get("google")
    if not login:
        return None, messages.GOOGLE_LOGIN_NEEDED, settings
    store = storage.SheetStorage(google_drive.SheetClient(login["access_token"]),
                                 st.session_state.setdefault("sheet_cache", {}))
    try:
        store.prepare()
        return store, None, settings
    except google_drive.AuthExpired as e:
        st.session_state.pop("google", None)
        return None, str(e), settings
    except google_drive.GoogleError as e:
        return None, str(e), settings


def _render_google_account(settings):
    """사이드바: 로그인 상태와 로그인·로그아웃 버튼."""
    login = st.session_state.get("google")
    if login:
        st.sidebar.caption(messages.GOOGLE_LOGGED_IN_AS.format(email=login.get("email") or "구글 계정"))
        if st.sidebar.button(messages.GOOGLE_LOGOUT_BUTTON, key="google-logout"):
            st.session_state.pop("google", None)
            st.session_state.pop("sheet_cache", None)
            st.rerun()
    else:
        cid, secret, redirect = settings
        st.sidebar.link_button(messages.GOOGLE_LOGIN_BUTTON,
                               google_drive.auth_url(cid, redirect, google_drive.make_state(secret)),
                               type="primary", icon="🔑")


DEFAULT_PERIOD = messages.PERIOD_ONGOING  # 처음 화면의 기간 필터
DEFAULT_REGION = "서울"                    # 처음 화면의 지역 필터(목록에 서울이 없으면 '전체')
PANE_HEIGHT = 720  # 전시 찾기의 목록 칸·상세 칸 높이(px). 두 칸은 각자 따로 스크롤된다.
SAVE_BUTTON_COLOR = "#1a73e8"
SAVE_BUTTON_HOVER = "#1557b0"

MY_CARD_TITLE_SIZE = "1.2rem"  # 내 전시 카드 제목: 본문 글자(1rem)의 120%
STATUS_HEADING_COLOR = SAVE_BUTTON_COLOR      # 전체 탭 상태 묶음 제목 색(파란색)
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
/* 전체 탭: [관심]/[관람예정]/[관람완료] 묶음 제목은 파란색, 묶음 사이 간격을 넓힌다 */
.st-key-all-tab h5 {{ color: {STATUS_HEADING_COLOR} !important; padding-top: 1.8rem !important; }}
/* 목록 칸·상세 칸 위의 제목 */
.pane-title {{ font-size: 1.2rem; font-weight: 700; color: {STATUS_HEADING_COLOR}; text-align: center;
               padding: 0.1rem 0 0.35rem 0.1rem; }}
div[class*="st-key-save-"] button {{
    background-color: {SAVE_BUTTON_COLOR} !important; border-color: {SAVE_BUTTON_COLOR} !important;
    color: #ffffff !important; font-weight: 600;
}}
div[class*="st-key-save-"] button:hover {{
    background-color: {SAVE_BUTTON_HOVER} !important; border-color: {SAVE_BUTTON_HOVER} !important;
}}
div[class*="st-key-save-"] button:disabled {{ opacity: 0.45; }}
</style>
"""


def list_pane_title(region, period):
    """목록 칸 제목. 예: '서울 - 진행중인 목록', '전체 - 진행예정인 목록', '부산 - 전체 기간 목록'."""
    period_text = {messages.PERIOD_ONGOING: "진행중인", messages.PERIOD_UPCOMING: "진행예정인"}.get(period, "전체 기간")
    return f"{region} - {period_text} 목록"


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


def _render_interest(db_path, r, today):
    eid = r["exhibition_id"]
    c1, c2 = st.columns([2, 1], vertical_alignment="bottom")
    with c1:
        picked = st.date_input(messages.PLANNED_DATE_LABEL, value=today, key=f"plan-date-{eid}",
                               format="YYYY-MM-DD")
    with c2:
        if st.button(messages.PLAN_BUTTON, key=f"plan-{eid}", type="primary"):
            _flash(repository.plan(db_path, eid, picked.isoformat() if picked else "", today=today),
                   messages.PLANNED_DONE)


def _render_planned(db_path, r, today):
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


def _render_done(db_path, r, today):
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
    has_review = r["review_rating"] is not None
    if has_review:
        st.write("★" * r["review_rating"] + "☆" * (5 - r["review_rating"]))
        st.write(r["review_text"])
    else:
        st.caption(messages.NO_REVIEW)
    rating = st.radio(messages.RATING_LABEL, [1, 2, 3, 4, 5],
                      index=(r["review_rating"] - 1) if has_review else 4,
                      format_func=lambda n: "★" * n, horizontal=True, key=f"rating-{eid}")
    text = st.text_area(messages.REVIEW_TEXT_LABEL, value=r["review_text"] or "", max_chars=1000,
                        key=f"review-text-{eid}")
    c1, c2 = st.columns(2)
    with c1:
        if st.button(messages.REVIEW_SAVE_BUTTON, key=f"review-{eid}", type="primary"):
            _flash(repository.write_review(db_path, eid, rating, text, today=today),
                   messages.REVIEW_SAVED_DONE)
    with c2:
        if has_review and st.button(messages.REVIEW_DELETE_BUTTON, key=f"review-del-{eid}"):
            _flash(repository.delete_review(db_path, eid, today=today), messages.REVIEW_DELETED_DONE)


_STATUS_CONTROLS = {
    repository.STATUS_INTEREST: _render_interest,
    repository.STATUS_PLANNED: _render_planned,
    repository.STATUS_DONE: _render_done,
}


def _date_line(r):
    parts = [f"{messages.PLANNED_DATE_LABEL} {r['planned_visit_date']}" if r["planned_visit_date"] else "",
             f"{messages.ACTUAL_DATE_LABEL} {r['actual_visit_date']}" if r.get("actual_visit_date") else ""]
    return " · ".join(p for p in parts if p)


def _render_all(db_path):
    """전체 탭: [관심] → [관람예정] → [관람완료] 제목 아래에 상태별 목록을 모아 본다.
    조작 버튼은 두지 않는다(같은 전시의 위젯이 상태 탭과 겹쳐 두 번 생기지 않도록)."""
    if not repository.count(db_path):
        st.write(messages.EMPTY_TAB)
        return
    st.caption(messages.ALL_TAB_NOTE)
    for status in repository.STATUSES:
        rows = repository.list_by_status(db_path, status)
        st.markdown(rf"##### \[{status}\] · {len(rows)}건")  # \[ \]: 대괄호를 글자 그대로 표시
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


def _render_my(db_path, today):
    if st.session_state.get("flash"):
        st.write(st.session_state.pop("flash"))
    tabs = st.tabs([messages.TAB_ALL, *messages.TAB_LABELS])
    with tabs[0], st.container(key="all-tab"):
        _render_all(db_path)
    for i, (tab, status) in enumerate(zip(tabs[1:], repository.STATUSES)):
        with tab, st.container(key=f"status-tab-{i}"):
            rows = repository.list_by_status(db_path, status)
            if not rows:
                st.write(messages.EMPTY_TAB)
            for r in rows:
                with st.container(border=True):
                    st.subheader(r["title"])
                    st.caption(" · ".join(x for x in (r["place"], r["region"],
                                                      f"{r['start_date']} ~ {r['end_date']}") if x))
                    if status == repository.STATUS_DONE:
                        dates = [f"{messages.PLANNED_DATE_LABEL} {r['planned_visit_date']}"
                                 if r["planned_visit_date"] else "",
                                 f"{messages.ACTUAL_DATE_LABEL} {r['actual_visit_date']}"
                                 if r["actual_visit_date"] else ""]
                        if any(dates):
                            st.caption(" · ".join(d for d in dates if d))
                    _STATUS_CONTROLS[status](db_path, r, today)
                    if st.button(messages.DELETE_RECORD_BUTTON, key=f"del-{r['exhibition_id']}"):
                        _flash(repository.delete(db_path, r["exhibition_id"]), messages.RECORD_DELETED_DONE)


def _render_assistant():
    """AI 도우미: 질문 → 에이전트(src/agent.py) → 답변 + 근거 문서 + 처리 과정."""
    st.caption(messages.ASSISTANT_INTRO)
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

    st.sidebar.title(messages.APP_TITLE)
    if gsettings:
        _render_google_account(gsettings)
    page = st.sidebar.radio("페이지", [messages.PAGE_FIND, messages.PAGE_MY, messages.PAGE_ASSISTANT],
                            format_func=lambda p: my_label if p == messages.PAGE_MY else p,
                            label_visibility="collapsed", key="page")
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
    period_options = [messages.PERIOD_ALL, messages.PERIOD_ONGOING, messages.PERIOD_UPCOMING]
    period = st.sidebar.selectbox(messages.FILTER_PERIOD_LABEL, period_options,
                                  index=period_options.index(DEFAULT_PERIOD), key="period")
    region_options = filters.region_options(base)
    region = st.sidebar.selectbox(
        messages.FILTER_REGION_LABEL, region_options,
        index=region_options.index(DEFAULT_REGION) if DEFAULT_REGION in region_options else 0,
        key="region")
    keyword = st.sidebar.text_input(messages.FILTER_KEYWORD_LABEL)
    art_only = st.sidebar.checkbox(messages.FILTER_ART_ONLY_LABEL, key="art-only")

    shown = filters.filter_exhibitions(base, today, period, region, keyword, art_only=art_only)
    selected_id = st.session_state.get("selected_id")
    selected = next((e for e in shown if e.exhibition_id == selected_id), None)

    if not db_ok:
        st.write(store_message)
    if st.session_state.get("flash"):
        st.write(st.session_state.pop("flash"))
    left_col, right_col = st.columns(2)
    # 칸 제목은 스크롤 영역 밖(위)에 두어 항상 보이게 한다
    left_col.html(f'<div class="pane-title">{html.escape(list_pane_title(region, period))}</div>')
    right_col.html(f'<div class="pane-title">{html.escape(messages.DETAIL_PANE_TITLE)}</div>')
    # 두 칸을 고정 높이 컨테이너로 감싸 각자 스크롤되게 한다(목록을 내려도 상세는 제자리).
    left = left_col.container(height=PANE_HEIGHT, key="list-pane")
    right = right_col.container(height=PANE_HEIGHT, key="detail-pane")
    with left:
        if exhibitions is None:
            st.write(messages.CULTURE_FAILED)
        elif not shown:
            st.write(messages.NO_RESULT)
        for e in shown:
            label = ("▶ " if e is selected else "") + e.title
            if st.button(label, key=f"pick-{e.exhibition_id}"):
                st.session_state["selected_id"] = e.exhibition_id
                selected = e
            state = messages.PERIOD_ONGOING if e.start_date <= today.isoformat() else messages.PERIOD_UPCOMING
            st.caption(" · ".join(x for x in (e.place, e.region, _period_text(e), state) if x))
    with right:
        if selected is None:
            st.write(messages.SELECT_EXHIBITION)
        else:
            with st.container(key="detail-head"):  # 제목·장소: 글자 크기를 줄이지 않는 영역
                st.header(selected.title)
                st.write(selected.place)
            st.write(_period_text(selected))
            if st.button(messages.SAVE_INTEREST_BUTTON, key=f"save-{selected.exhibition_id}",
                         type="primary", icon="⭐", disabled=not db_ok):
                _flash(repository.save(db_path, selected), messages.SAVED_DONE)
            data = _detail_data(selected)
            if data["summary"]:
                st.subheader(messages.SUMMARY_HEADING)
                st.write(data["summary"])
            search_api.render_related(st, data["related"])


main()
