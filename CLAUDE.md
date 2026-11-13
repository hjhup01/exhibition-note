# 작업 규칙 (Claude Code)

## 1. 작업 기록: history.md
- 작업 하나를 마칠 때마다(코드 변경, 설정 안내, 원인 분석 모두) `history.md` **맨 아래에 이어서** 적는다.
- 순서는 시간순으로 한다. 날짜가 바뀌면 `## YYYY-MM-DD (요일)` 제목을 새로 단다.
- 항목 번호는 앞 항목에 이어 붙인다.
- 형식:
  ```
  N. **한 줄 제목**
     - 요청: 사용자가 요청한 것(짧게)
     - 원인: (문제 수정이면) 원인
     - 한 일: 바꾼 내용
     - 결과: 커밋 해시(예: `8bf85a0`) 또는 '안내만 함', 미해결이면 그렇다고 적는다
  ```
- 커밋하는 작업이면 history.md도 같은 커밋에 넣는다.
- 비밀값(API 키, 클라이언트 비밀값, 토큰)과 개인 이메일은 적지 않는다.

## 2. 대화
- 사용자에게는 한국어로 답한다.

## 3. 프로젝트 규칙
- **삭제는 항상 두 단계로 한다.** 화면의 모든 삭제는 '삭제 버튼 → 경고 + [삭제]/[취소]'를 거친다.
  - `src/app.py`의 `_ask_delete_button` / `_confirm_delete`를 쓴다.
  - `tests/test_delete_rule.py`가 이 규칙을 검사한다.
- **비밀값을 올리지 않는다.** `.env`, `.streamlit/secrets.toml`, `*.db`는 Git에 올리지 않는다. 커밋 전에 바뀐 내용에 비밀값이 없는지 확인한다.
- **화면 파일은 경계를 지킨다.** `src/app.py`는 `exhibition_app` 패키지만 부른다. `requests`·`sqlite3`·`urllib` 등을 직접 쓰지 않는다(`tests/test_verifiability.py`).
- **AI 도구 동작은 평가 기준이다.** 바꾸면 평가 결과가 달라지므로 신중히 한다(예: `search_exhibitions`의 키워드는 제목만).

## 4. 실행·확인 명령
- 테스트:
  ```
  uv run --no-project --quiet --python 3.12 --with-requirements requirements.txt python -m pytest -q
  ```
- 코드 검사:
  ```
  uvx ruff check src app.py tests --select F,E9,B
  ```
- 앱:
  ```
  uv run --no-project --quiet --python 3.12 --with-requirements requirements.txt streamlit run src/app.py
  ```
- API:
  ```
  uv run --no-project --quiet --python 3.12 --with-requirements requirements.txt uvicorn api:app --app-dir src --port 8000
  ```
- Streamlit 1.67 주의:
  - 입력 칸 DOM이 react-aria 구조다(`data-baseweb` 선택자가 맞지 않음).
  - 펼침 상자·탭은 `key` + `on_change="rerun"`일 때만 상태를 기억한다.
- 배포:
  - Streamlit Cloud, Main file = 맨 위 `app.py`.
  - `main`에 푸시하면 자동 반영된다.
