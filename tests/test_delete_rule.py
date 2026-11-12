"""삭제 공통 규칙: 화면의 모든 삭제는 '삭제 버튼 → 경고 + [삭제]/[취소]' 두 단계를 거친다.

app.py를 읽어 규칙을 검사한다. 새 삭제 버튼을 만들 때 확인 단계를 빠뜨리면 이 테스트가 실패한다.
"""
import ast
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "src" / "app.py"
TREE = ast.parse(APP.read_text(encoding="utf-8"))
# 실제로 지우는 저장소 함수 → 이것을 부를 수 있는, 확인 버튼 콜백 함수
DELETERS = {"delete", "delete_review", "remove_photo"}
CONFIRMED_CALLBACKS = {"_delete_record", "_delete_review", "_delete_photo"}


def _func_of(node):
    for f in ast.walk(TREE):
        if isinstance(f, ast.FunctionDef) and any(n is node for n in ast.walk(f)):
            inner = [g for g in ast.walk(f) if isinstance(g, ast.FunctionDef) and g is not f
                     and any(n is node for n in ast.walk(g))]
            if not inner:
                return f.name
    return None


def test_repository_deletes_only_inside_confirmed_callbacks():
    calls = [n for n in ast.walk(TREE) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and isinstance(n.func.value, ast.Name) and n.func.value.id == "repository" and n.func.attr in DELETERS]
    assert calls, "삭제 호출을 찾지 못했다"
    for c in calls:
        assert _func_of(c) in CONFIRMED_CALLBACKS, f"{c.func.attr}가 확인 없이 불릴 수 있다(line {c.lineno})"


def test_confirmed_callbacks_are_only_run_from_confirm_step():
    for n in ast.walk(TREE):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in CONFIRMED_CALLBACKS:
            raise AssertionError(f"{n.func.id}를 직접 부르면 안 된다(line {n.lineno}): _confirm_delete로 넘긴다")
    passed = {n.args[2].id for n in ast.walk(TREE) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
              and n.func.id == "_confirm_delete"}  # _confirm_delete(key, 문구, 콜백, 인자)
    assert passed == CONFIRMED_CALLBACKS


def test_every_delete_button_uses_ask_step():
    for n in ast.walk(TREE):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "button"):
            continue
        label = n.args[0] if n.args else None
        name = label.attr if isinstance(label, ast.Attribute) else ""
        assert not (name.endswith("_BUTTON") and "DELETE" in name), \
            f"삭제 버튼({name})은 _ask_delete_button으로 만든다(line {n.lineno})"
