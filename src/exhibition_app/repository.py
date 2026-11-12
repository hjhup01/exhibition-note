"""저장 규칙(saved_exhibition SQLite). 위젯과 독립적이며 예외를 밖으로 던지지 않는다."""
import os
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

from . import messages

STATUS_INTEREST = "관심"
STATUS_PLANNED = "관람예정"
STATUS_DONE = "관람완료"
STATUSES = (STATUS_INTEREST, STATUS_PLANNED, STATUS_DONE)
SNAPSHOT_FIELDS = ("exhibition_id", "title", "category", "region", "place", "start_date", "end_date")
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}", re.ASCII)

SCHEMA = """
CREATE TABLE IF NOT EXISTS saved_exhibition (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exhibition_id TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    category TEXT NOT NULL,
    region TEXT NOT NULL,
    place TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT '관심',
    planned_visit_date TEXT,
    actual_visit_date TEXT,
    review_rating INTEGER,
    review_text TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""


@dataclass(frozen=True)
class WriteResult:
    ok: bool
    message: Optional[str] = None


_OK = WriteResult(True, None)


class _Reject(Exception):
    pass


def _connect(db_path):
    conn = sqlite3.connect(str(db_path), timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path) -> WriteResult:
    """스키마를 만든다. 기본 경로면 상위 디렉터리도 만든다. 열 수 없으면 STORE_UNAVAILABLE."""
    try:
        os.makedirs(os.path.dirname(os.path.abspath(str(db_path))), exist_ok=True)
        with closing(_connect(db_path)) as conn, conn:
            conn.execute(SCHEMA)
            cols = {r[1] for r in conn.execute("PRAGMA table_info(saved_exhibition)")}
            if "actual_visit_date" not in cols:  # 이전 버전 DB: 실제 관람일 열을 추가한다
                conn.execute("ALTER TABLE saved_exhibition ADD COLUMN actual_visit_date TEXT")
        return _OK
    except (OSError, sqlite3.Error):
        return WriteResult(False, messages.STORE_UNAVAILABLE)


def _now(now=None):
    return (now or datetime.now()).isoformat()


def _valid_date(value):
    if not isinstance(value, str) or not _DATE_RE.fullmatch(value):
        return False
    try:
        date(int(value[:4]), int(value[5:7]), int(value[8:]))
    except ValueError:
        return False
    return True


def _get(exhibition, field):
    if isinstance(exhibition, dict):
        return exhibition[field]
    return getattr(exhibition, field)


def save(db_path, exhibition, today: Optional[date] = None, now: Optional[datetime] = None) -> WriteResult:
    """전시 스냅샷을 '관심' 상태로 저장한다."""
    try:
        values = [_get(exhibition, f) for f in SNAPSHOT_FIELDS]
        stamp = _now(now)
        with closing(_connect(db_path)) as conn, conn:
            conn.execute(
                "INSERT INTO saved_exhibition (exhibition_id, title, category, region, place,"
                " start_date, end_date, status, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)", values + [STATUS_INTEREST, stamp, stamp])
        return _OK
    except sqlite3.IntegrityError:
        return WriteResult(False, messages.ALREADY_SAVED)
    except Exception:
        return WriteResult(False, messages.SAVE_FAILED)


def _update(db_path, exhibition_id, step, now=None):
    """한 트랜잭션에서 행을 읽고 step(row)이 (SET 절, 값 목록)을 돌려주면 갱신한다."""
    try:
        with closing(_connect(db_path)) as conn, conn:
            row = conn.execute("SELECT * FROM saved_exhibition WHERE exhibition_id = ?",
                               (exhibition_id,)).fetchone()
            if row is None:
                return WriteResult(False, messages.NOT_FOUND)
            sets, params = step(row)
            conn.execute(f"UPDATE saved_exhibition SET {sets}, updated_at=? WHERE exhibition_id=?",
                         params + [_now(now), exhibition_id])
        return _OK
    except _Reject as r:
        return WriteResult(False, str(r))
    except Exception:
        return WriteResult(False, messages.SAVE_FAILED)


def plan(db_path, exhibition_id, planned_visit_date, today: Optional[date] = None, now: Optional[datetime] = None) -> WriteResult:
    """관심 → 관람예정."""
    if not _valid_date(planned_visit_date):
        return WriteResult(False, messages.INVALID_PLANNED_DATE)

    def step(row):
        if row["status"] != STATUS_INTEREST:
            raise _Reject(messages.INVALID_TRANSITION)
        return "status=?, planned_visit_date=?", [STATUS_PLANNED, planned_visit_date]
    return _update(db_path, exhibition_id, step, now)


def _check_actual_date(actual_visit_date, today):
    """실제 관람일: 실제 달력 날짜(YYYY-MM-DD)이고, today가 주어지면 그 이후일 수 없다. 문제가 있으면 문구."""
    if not _valid_date(actual_visit_date):
        return messages.INVALID_ACTUAL_DATE
    if today is not None and actual_visit_date > today.isoformat():
        return messages.FUTURE_ACTUAL_DATE
    return None


def complete(db_path, exhibition_id, actual_visit_date: Optional[str] = None,
             today: Optional[date] = None, now: Optional[datetime] = None) -> WriteResult:
    """관람예정 → 관람완료 (관람예정일 유지). actual_visit_date를 주면 실제 관람일로 함께 저장한다."""
    if actual_visit_date is not None:
        problem = _check_actual_date(actual_visit_date, today)
        if problem:
            return WriteResult(False, problem)

    def step(row):
        if row["status"] != STATUS_PLANNED:
            raise _Reject(messages.INVALID_TRANSITION)
        return "status=?, actual_visit_date=?", [STATUS_DONE, actual_visit_date]
    return _update(db_path, exhibition_id, step, now)


def change_actual_date(db_path, exhibition_id, actual_visit_date, today: Optional[date] = None,
                       now: Optional[datetime] = None) -> WriteResult:
    """관람완료 상태에서만 실제 관람일을 바꾼다."""
    problem = _check_actual_date(actual_visit_date, today)
    if problem:
        return WriteResult(False, problem)

    def step(row):
        if row["status"] != STATUS_DONE:
            raise _Reject(messages.ACTUAL_DATE_STATE)
        return "actual_visit_date=?", [actual_visit_date]
    return _update(db_path, exhibition_id, step, now)


def change_planned_date(db_path, exhibition_id, planned_visit_date, today: Optional[date] = None, now: Optional[datetime] = None) -> WriteResult:
    if not _valid_date(planned_visit_date):
        return WriteResult(False, messages.INVALID_PLANNED_DATE)

    def step(row):
        if row["status"] != STATUS_PLANNED:
            raise _Reject(messages.PLANNED_DATE_STATE)
        return "planned_visit_date=?", [planned_visit_date]
    return _update(db_path, exhibition_id, step, now)


def write_review(db_path, exhibition_id, rating, text, today: Optional[date] = None, now: Optional[datetime] = None) -> WriteResult:
    if isinstance(rating, bool) or not isinstance(rating, int) or not 1 <= rating <= 5:
        return WriteResult(False, messages.INVALID_RATING)
    if not isinstance(text, str) or not 1 <= len(text.strip()) <= 1000:
        return WriteResult(False, messages.INVALID_REVIEW_TEXT)
    text = text.strip()

    def step(row):
        if row["status"] != STATUS_DONE:
            raise _Reject(messages.REVIEW_STATE)
        return "review_rating=?, review_text=?", [rating, text]
    return _update(db_path, exhibition_id, step, now)


def delete_review(db_path, exhibition_id, today: Optional[date] = None, now: Optional[datetime] = None) -> WriteResult:
    def step(row):
        if row["status"] != STATUS_DONE:
            raise _Reject(messages.REVIEW_STATE)
        return "review_rating=NULL, review_text=NULL", []
    return _update(db_path, exhibition_id, step, now)


def delete(db_path, exhibition_id) -> WriteResult:
    """전시 기록(행 전체) 삭제."""
    try:
        with closing(_connect(db_path)) as conn, conn:
            n = conn.execute("DELETE FROM saved_exhibition WHERE exhibition_id = ?",
                             (exhibition_id,)).rowcount
        return _OK if n else WriteResult(False, messages.NOT_FOUND)
    except Exception:
        return WriteResult(False, messages.SAVE_FAILED)


def list_by_status(db_path, status) -> list:
    """updated_at 내림차순(같으면 exhibition_id 오름차순). 실패하면 빈 목록."""
    try:
        with closing(_connect(db_path)) as conn:
            rows = conn.execute("SELECT * FROM saved_exhibition WHERE status = ?"
                                " ORDER BY updated_at DESC, exhibition_id ASC", (status,)).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def list_all(db_path) -> list:
    """모든 상태의 행. updated_at 내림차순(같으면 exhibition_id 오름차순). 실패하면 빈 목록."""
    try:
        with closing(_connect(db_path)) as conn:
            rows = conn.execute("SELECT * FROM saved_exhibition"
                                " ORDER BY updated_at DESC, exhibition_id ASC").fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def count(db_path) -> int:
    try:
        with closing(_connect(db_path)) as conn:
            return conn.execute("SELECT COUNT(*) FROM saved_exhibition").fetchone()[0]
    except Exception:
        return 0


def is_saved(db_path, exhibition_id) -> bool:
    try:
        with closing(_connect(db_path)) as conn:
            return conn.execute("SELECT 1 FROM saved_exhibition WHERE exhibition_id = ?",
                                (exhibition_id,)).fetchone() is not None
    except Exception:
        return False
