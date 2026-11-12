"""Streamlit Cloud 진입점: 기존 배포 설정(Main file path = app.py)을 그대로 쓰기 위한 얇은 실행 파일.

실제 화면 코드는 src/app.py에 있다. 로컬에서는 `streamlit run src/app.py`와 `streamlit run app.py` 모두 된다.
"""
import runpy
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))  # src/app.py가 exhibition_app·agent 등을 찾을 수 있게

runpy.run_path(str(SRC / "app.py"), run_name="__main__")
