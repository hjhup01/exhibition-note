"""기록 저장 위치 선택: 로컬 SQLite 또는 사용자 구글 드라이브의 시트.

저장 규칙(상태 전환·날짜·별점 검사 등)은 repository.py 하나뿐이다. 구글 시트를 쓸 때는
1) 세션 처음에 시트 내용을 세션 전용 임시 SQLite 파일로 내려받고(prepare),
2) repository 함수를 그 파일에 그대로 실행한 뒤,
3) 쓰기가 성공하면 파일 내용을 시트에 통째로 다시 올린다(after_write).
올리기에 실패하면 임시 파일을 버려 다음 실행 때 시트 내용으로 되돌아간다.
"""
import os
import re
import sqlite3
import tempfile
import uuid
from contextlib import closing

from . import config, google_drive, repository

COLUMNS = google_drive.COLUMNS


class LocalStorage:
    """이 PC의 SQLite 파일(DB_PATH)."""
    kind = "local"

    def __init__(self, db_path=None):
        self.db_path = db_path or config.db_path()

    def prepare(self):
        return self.db_path

    def after_write(self):
        pass

    # 관람 사진: DB 파일 옆 photos 폴더에 <uuid>.jpg로 둔다
    def _photo_dir(self):
        return os.path.join(os.path.dirname(os.path.abspath(str(self.db_path))), "photos")

    def _photo_path(self, photo_id):
        if not _LOCAL_PHOTO_ID.fullmatch(str(photo_id)):  # 경로 조작 방지: 우리가 만든 이름만
            return None
        return os.path.join(self._photo_dir(), photo_id)

    def save_photo(self, name, data, mime="image/jpeg"):
        os.makedirs(self._photo_dir(), exist_ok=True)
        photo_id = f"{uuid.uuid4().hex}.jpg"
        with open(self._photo_path(photo_id), "wb") as f:
            f.write(data)
        return photo_id

    def load_photo(self, photo_id):
        path = self._photo_path(photo_id)
        if not path or not os.path.exists(path):
            return None
        with open(path, "rb") as f:
            return f.read()

    def delete_photo(self, photo_id):
        path = self._photo_path(photo_id)
        if path and os.path.exists(path):
            os.remove(path)


_LOCAL_PHOTO_ID = re.compile(r"[0-9a-f]{32}\.jpg")


def _load_into_db(db_path, rows):
    with closing(sqlite3.connect(db_path)) as conn, conn:
        conn.execute("DELETE FROM saved_exhibition")
        conn.executemany(
            f"INSERT INTO saved_exhibition ({', '.join(COLUMNS)}) VALUES ({', '.join('?' * len(COLUMNS))})",
            [[r.get(c) for c in COLUMNS] for r in rows])


def _dump_db(db_path):
    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(f"SELECT {', '.join(COLUMNS)} FROM saved_exhibition"
                            " ORDER BY created_at ASC, exhibition_id ASC").fetchall()
    return [dict(r) for r in rows]


class SheetStorage:
    """로그인한 사용자 드라이브의 '전시노트 기록' 시트. cache는 세션별 dict(st.session_state 일부)."""
    kind = "google"

    def __init__(self, client, cache):
        self.client = client
        self.cache = cache

    def prepare(self):
        """시트를 찾거나 만들고 내용을 임시 SQLite로 내려받는다(세션당 한 번). 임시 파일 경로를 돌려준다."""
        if self.cache.get("db_path") and os.path.exists(self.cache["db_path"]):
            return self.cache["db_path"]
        sid = self.client.find_or_create()
        rows = self.client.read_rows(sid)
        folder = self.cache.get("dir") or tempfile.mkdtemp(prefix="exhibition-note-")
        db_path = os.path.join(folder, "sheet.db")
        if os.path.exists(db_path):
            os.remove(db_path)
        if not repository.init_db(db_path).ok:
            raise google_drive.GoogleError(google_drive.messages.GOOGLE_SHEET_FAILED)
        _load_into_db(db_path, rows)
        self.cache.update({"dir": folder, "db_path": db_path, "sid": sid})
        return db_path

    def after_write(self):
        """임시 SQLite 내용을 시트에 올린다. 실패하면 임시 파일을 버리고 GoogleError."""
        try:
            self.client.write_rows(self.cache["sid"], _dump_db(self.cache["db_path"]))
        except Exception:
            self.reset()
            raise

    # 관람 사진: 사용자 드라이브의 '전시노트 사진' 폴더. 받은 사진은 세션 동안 기억한다(다시 그릴 때마다 받지 않게).
    def save_photo(self, name, data, mime="image/jpeg"):
        folder = self.cache.get("photo_folder") or self.client.find_or_create_photo_folder()
        self.cache["photo_folder"] = folder
        photo_id = self.client.upload_photo(folder, name, data, mime)
        self.cache.setdefault("photos", {})[photo_id] = data
        return photo_id

    def load_photo(self, photo_id):
        got = self.cache.setdefault("photos", {})
        if photo_id not in got:
            got[photo_id] = self.client.download_photo(photo_id)
        return got[photo_id]

    def delete_photo(self, photo_id):
        self.cache.setdefault("photos", {}).pop(photo_id, None)
        self.client.delete_photo(photo_id)

    def reset(self):
        path = self.cache.pop("db_path", None)
        self.cache.pop("sid", None)
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass
