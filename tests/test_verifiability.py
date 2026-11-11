"""AC 검증 가능성: requirements.txt·tests/ 구성, AC 1~11 테스트 존재, app.py 경계."""
import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# AC 번호 -> 해당 AC를 검증하는 테스트 파일
AC_TEST_FILES = {
    1: "test_exhibition_list.py",
    2: "test_filters.py",
    3: "test_exhibition_failures.py",
    4: "test_related.py",
    5: "test_summary.py",
    6: "test_prompt_safety.py",
    7: "test_secrets.py",
    8: "test_my_exhibitions.py",
    9: "test_status.py",
    10: "test_reviews.py",
    11: "test_storage_failure.py",
}


def test_ac13_requirements_lists_required_packages():
    names = {
        re.split(r"[<>=\[; ]", line.strip(), maxsplit=1)[0].lower()
        for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }
    for pkg in ("streamlit", "requests", "python-dotenv", "langchain-aws", "langsmith", "pytest"):
        assert pkg in names


def test_ac13_each_ac_1_to_11_has_a_test_function():
    for ac, fname in AC_TEST_FILES.items():
        path = ROOT / "tests" / fname
        assert path.is_file(), f"AC {ac}: {fname} 없음"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        tests = [n for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")]
        assert tests, f"AC {ac}: {fname}에 테스트 함수 없음"


def test_ac13_app_py_only_calls_package_modules():
    tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
    imported = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            imported |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module:
            imported.add(n.module.split(".")[0])
    forbidden = {"requests", "sqlite3", "boto3", "botocore", "langchain_aws", "urllib", "http"}
    assert not (imported & forbidden)
    assert "exhibition_app" in imported
