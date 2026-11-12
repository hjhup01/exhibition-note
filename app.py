"""Streamlit Cloud 진입점: 기존 배포 설정(Main file path = app.py)을 그대로 쓰기 위한 얇은 실행 파일.

실제 화면 코드는 src/app.py에 있다. 로컬에서는 `streamlit run src/app.py`와 `streamlit run app.py` 모두 된다.

Streamlit Cloud는 GitHub에 새 커밋이 올라오면 앱을 다시 시작하지 않고 화면 코드만 다시 읽는다.
그때 메모리에 남은 예전 모듈(exhibition_app.messages 등)과 새 화면 코드가 섞이면 오류가 나므로,
src 아래 .py 파일이 바뀐 것을 알아채면 이 프로젝트의 모듈을 버리고 새로 불러오게 한다.
"""
import runpy
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))  # src/app.py가 exhibition_app·agent 등을 찾을 수 있게

_PROJECT_MODULES = ("exhibition_app", "agent", "tools", "retriever", "guardrails", "build_corpus")


def _source_stamp():
    """src 아래 .py 파일들의 (마지막 수정 시각, 개수). 코드가 바뀌면 달라진다."""
    files = list(SRC.rglob("*.py"))
    return max((f.stat().st_mtime for f in files), default=0), len(files)


def _forget_stale_modules():
    stamp = _source_stamp()
    if getattr(sys, "_exhibition_src_stamp", None) not in (None, stamp):
        for name in list(sys.modules):
            if name.split(".")[0] in _PROJECT_MODULES:
                del sys.modules[name]
    sys._exhibition_src_stamp = stamp  # 다시 실행되어도 남도록 sys에 둔다(이 파일의 전역 변수는 매번 새로 생김)


_forget_stale_modules()
runpy.run_path(str(SRC / "app.py"), run_name="__main__")
