"""관람 사진: 이미지 검사·축소, 기록에 사진 붙이기·빼기, 로컬·구글 드라이브 저장, 화면."""
import io
import json
import sqlite3
from datetime import date
from pathlib import Path

import pytest
from PIL import Image
from streamlit.testing.v1 import AppTest

from exhibition_app import config, culture_api, google_drive, messages, photos, repository, storage
from exhibition_app.culture_api import Exhibition

APP = str(Path(__file__).resolve().parent.parent / "src" / "app.py")
TODAY = date(2026, 11, 12)
EX = Exhibition("1", "빛의 층위", "미술", "서울", "한강아트센터", "2026-10-02", "2027-01-18")


def png(w=40, h=30, color=(200, 120, 40)):
    out = io.BytesIO()
    Image.new("RGB", (w, h), color).save(out, "PNG")
    return out.getvalue()


def done_record(db):
    repository.init_db(db)
    assert repository.save(db, EX).ok
    assert repository.plan(db, "1", "2026-11-01").ok
    assert repository.complete(db, "1", "2026-11-02", today=TODAY).ok


# ---------- 이미지 ----------

def test_prepare_image_makes_smaller_jpeg():
    out = photos.prepare_image(png(4000, 3000))
    img = Image.open(io.BytesIO(out))
    assert img.format == "JPEG" and max(img.size) == photos.MAX_SIDE


def test_prepare_image_drops_exif_and_applies_rotation():
    src = io.BytesIO()
    exif = Image.Exif()
    exif[0x0112] = 6  # 휴대폰 사진: 90도 돌려 보여야 함
    exif[0x8825] = {1: "N"}  # GPS 정보(지워져야 함)
    Image.new("RGB", (60, 20)).save(src, "JPEG", exif=exif)
    img = Image.open(io.BytesIO(photos.prepare_image(src.getvalue())))
    assert img.size == (20, 60)  # 세로로 세워짐
    assert not img.getexif()  # 위치 등 EXIF는 남지 않음


@pytest.mark.parametrize("data", [b"", b"not an image", b"GIF89a" + b"\x00" * 10])
def test_prepare_image_rejects_non_images(data):
    with pytest.raises(photos.PhotoError) as e:
        photos.prepare_image(data)
    assert str(e.value) == messages.PHOTO_INVALID


def test_prepare_image_rejects_too_large():
    with pytest.raises(photos.PhotoError) as e:
        photos.prepare_image(b"x" * (photos.MAX_UPLOAD_BYTES + 1))
    assert str(e.value) == messages.PHOTO_TOO_LARGE


def test_parse_and_dump_ids():
    assert photos.parse_ids(None) == [] and photos.parse_ids("깨진값") == [] and photos.parse_ids("{}") == []
    assert photos.parse_ids(photos.dump_ids(["a", "b"])) == ["a", "b"]
    assert photos.dump_ids([]) is None


# ---------- 기록 ----------

def test_add_photo_only_when_done_and_up_to_three(tmp_path):
    db = str(tmp_path / "x.db")
    repository.init_db(db)
    repository.save(db, EX)
    r = repository.add_photo(db, "1", "p0")
    assert not r.ok and r.message == messages.PHOTO_STATE
    repository.plan(db, "1", "2026-11-01")
    repository.complete(db, "1", "2026-11-02", today=TODAY)
    for i in range(3):
        assert repository.add_photo(db, "1", f"p{i}").ok
    r = repository.add_photo(db, "1", "p3")
    assert not r.ok and r.message == messages.PHOTO_LIMIT
    assert repository.photo_ids_of(db, "1") == ["p0", "p1", "p2"]
    assert repository.remove_photo(db, "1", "p1").ok
    assert repository.photo_ids_of(db, "1") == ["p0", "p2"]
    assert repository.remove_photo(db, "1", "nope").message == messages.NOT_FOUND


def test_old_db_gets_photo_column(tmp_path):
    db = str(tmp_path / "old.db")
    with sqlite3.connect(db) as c:  # 사진 열이 없던 예전 DB
        c.execute(repository.SCHEMA.replace(",\n    photo_ids TEXT", ""))
    assert repository.init_db(db).ok
    with sqlite3.connect(db) as c:
        assert "photo_ids" in {r[1] for r in c.execute("PRAGMA table_info(saved_exhibition)")}


# ---------- 저장소 ----------

def test_local_storage_photos_roundtrip_and_safe_ids(tmp_path):
    st_ = storage.LocalStorage(str(tmp_path / "x.db"))
    pid = st_.save_photo("a.jpg", b"JPEG")
    assert st_.load_photo(pid) == b"JPEG"
    assert (tmp_path / "photos" / pid).exists()
    assert st_.load_photo("../x.db") is None and st_.load_photo("..\\x.db") is None  # 경로 조작 막기
    st_.delete_photo(pid)
    assert st_.load_photo(pid) is None


class FakeClient:
    def __init__(self):
        self.files, self.folder_calls, self.downloads = {}, 0, 0

    def find_or_create_photo_folder(self):
        self.folder_calls += 1
        return "F1"

    def upload_photo(self, folder, name, data, mime):
        fid = f"D{len(self.files) + 1}"
        self.files[fid] = (folder, name, data, mime)
        return fid

    def download_photo(self, fid):
        self.downloads += 1
        return self.files[fid][2]

    def delete_photo(self, fid):
        del self.files[fid]


def test_sheet_storage_photos_use_drive_folder_and_session_cache():
    client, cache = FakeClient(), {}
    st_ = storage.SheetStorage(client, cache)
    a = st_.save_photo("1-a.jpg", b"A", "image/jpeg")
    b = st_.save_photo("1-b.jpg", b"B", "image/jpeg")
    assert client.folder_calls == 1 and client.files[a][0] == "F1"  # 폴더는 한 번만 찾는다
    assert st_.load_photo(a) == b"A" and client.downloads == 0  # 방금 올린 사진은 다시 받지 않는다
    cache["photos"].clear()
    assert st_.load_photo(b) == b"B" and st_.load_photo(b) == b"B" and client.downloads == 1
    st_.delete_photo(a)
    assert a not in client.files


class Resp:
    def __init__(self, status, payload=None, content=None):
        self.status_code = status
        self._payload = payload
        self.content = content if content is not None else (json.dumps(payload).encode() if payload else b"")

    def json(self):
        return self._payload


def test_sheet_client_uploads_multipart_into_folder_and_downloads():
    calls = []

    class Http:
        def request(self, method, url, headers=None, timeout=None, params=None, json=None, data=None):
            calls.append((method, url, params, headers, data, timeout))
            if url == google_drive.UPLOAD_URL:
                return Resp(200, {"id": "D9"})
            if params and params.get("alt") == "media":
                return Resp(200, content=b"IMG")
            return Resp(200, {"files": []} if method == "GET" else {"id": "F1"})

    client = google_drive.SheetClient("TOKEN", http=Http())
    assert client.find_or_create_photo_folder() == "F1"
    assert calls[-1][0] == "POST"  # 폴더가 없으면 만든다
    assert client.upload_photo("F1", "1-a.jpg", b"\xff\xd8JPEG") == "D9"
    method, url, params, headers, body, timeout = calls[-1]
    assert params["uploadType"] == "multipart" and headers["Content-Type"].startswith("multipart/related")
    assert b'"parents": ["F1"]' in body and b"\xff\xd8JPEG" in body and timeout == google_drive.UPLOAD_TIMEOUT_SECONDS
    assert headers["Authorization"] == "Bearer TOKEN"
    assert client.download_photo("D9") == b"IMG"


def test_sheet_client_photo_errors_are_korean_messages():
    class Down:
        def request(self, *a, **k):
            return Resp(500, {"error": {}})

    client = google_drive.SheetClient("TOKEN", http=Down())
    with pytest.raises(google_drive.GoogleError) as e:
        client.upload_photo("F1", "a.jpg", b"x")
    assert str(e.value) == messages.PHOTO_UPLOAD_FAILED


def test_old_sheet_without_photo_column_reads_as_empty():
    header = [c for c in google_drive.COLUMNS if c != "photo_ids"]
    rows = google_drive.values_to_rows([header, ["1", "A"] + [""] * (len(header) - 2)])
    assert rows[0]["photo_ids"] is None


# ---------- 화면 ----------

@pytest.fixture
def my_page(tmp_path, monkeypatch):
    db = str(tmp_path / "x.db")
    monkeypatch.setenv("DB_PATH", db)
    monkeypatch.setattr(config, "today_kst", lambda: TODAY)
    monkeypatch.setattr(culture_api, "fetch_exhibitions", lambda *a, **k: [EX])
    done_record(db)
    return db


def open_done_tab(expand=True):
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.radio(key="page").set_value(messages.PAGE_MY).run()
    if expand:  # 관람완료 탭과 전체 탭 목록에서 전시를 펼친다
        at.session_state["rec-관람완료-1"] = True
        at.session_state["all-1"] = True
        at.run()
    assert not at.exception
    return at


def test_done_tab_shows_photo_section_and_uploader(my_page):
    at = open_done_tab()
    heads = [m.value for m in at.markdown]
    assert f"**{messages.PHOTO_HEADING.format(count=0, limit=3)}**" in heads
    assert at.get("file_uploader")  # 사진 고르기 칸


def test_photos_show_in_done_and_all_tabs_and_can_be_deleted(my_page):
    st_ = storage.LocalStorage(my_page)
    pid = st_.save_photo("a.jpg", photos.prepare_image(png()))
    assert repository.add_photo(my_page, "1", pid).ok
    at = open_done_tab()
    assert len(at.get("image")) == 2  # 관람완료 탭 1장 + 전체 탭 작은 사진 1장
    at.button(key=f"photo-del-1-{pid}").click().run()
    assert messages.PHOTO_DELETE_CONFIRM in [w.value for w in at.warning]
    assert repository.photo_ids_of(my_page, "1") == [pid]  # 아직 지우지 않았다
    at.button(key=f"photo-del-1-{pid}-yes").click().run()
    assert not at.exception
    assert messages.PHOTO_DELETED_DONE in [m.value for m in at.markdown]
    assert repository.photo_ids_of(my_page, "1") == [] and st_.load_photo(pid) is None


def test_deleting_record_removes_its_photo_files(my_page):
    st_ = storage.LocalStorage(my_page)
    pid = st_.save_photo("a.jpg", photos.prepare_image(png()))
    repository.add_photo(my_page, "1", pid)
    at = open_done_tab()
    at.button(key="del-1").click().run()
    at.button(key="del-1-yes").click().run()
    assert not at.exception
    assert st_.load_photo(pid) is None


def test_sheet_storage_remembers_missing_photo_but_not_expired_login():
    class Missing(FakeClient):
        def download_photo(self, fid):
            self.downloads += 1
            if fid == "gone":
                raise google_drive.GoogleError(messages.PHOTO_LOAD_FAILED)
            raise google_drive.AuthExpired(messages.GOOGLE_LOGIN_EXPIRED)

    client, cache = Missing(), {}
    st_ = storage.SheetStorage(client, cache)
    assert st_.load_photo("gone") is None and st_.load_photo("gone") is None
    assert client.downloads == 1  # 지워진 사진은 한 번만 시도
    for _ in range(2):
        with pytest.raises(google_drive.AuthExpired):
            st_.load_photo("expired")
    assert client.downloads == 3  # 로그인 만료는 기억하지 않는다


def test_status_tabs_show_one_line_list_and_load_photos_only_when_opened(my_page, monkeypatch):
    st_ = storage.LocalStorage(my_page)
    pid = st_.save_photo("a.jpg", photos.prepare_image(png()))
    repository.add_photo(my_page, "1", pid)
    repository.write_review(my_page, "1", 4, "좋았다", today=TODAY)
    loads = []
    real = storage.LocalStorage.load_photo
    monkeypatch.setattr(storage.LocalStorage, "load_photo", lambda self, p: loads.append(p) or real(self, p))
    at = open_done_tab(expand=False)
    done = at.tabs[3]
    assert [e.label for e in done.expander] == ["빛의 층위 · 관람일 2026-11-02 · ★★★★☆ · 📷 1"]
    assert messages.RECORD_LIST_NOTE in [c.value for c in done.caption]
    assert not done.get("image") and not done.get("file_uploader")  # 접혀 있으면 사진을 불러오지 않는다
    at.session_state["rec-관람완료-1"] = True
    at.run()
    assert len(at.tabs[3].get("image")) == 1 and at.tabs[3].get("file_uploader")


def test_record_label_escapes_markdown_and_shows_status_info():
    src = open(APP, encoding="utf-8").read()
    ns = {}
    start = src.index("_MD_SPECIAL = ")
    end = src.index("def _render_my(")
    exec("from exhibition_app import messages, photos, repository\n" + src[start:end], ns)
    label = ns["record_label"]
    base = {"title": "[특별전] *빛*", "place": "P", "end_date": "2026-12-31", "planned_visit_date": "2026-11-20",
            "actual_visit_date": None, "review_rating": None, "photo_ids": None}
    assert label({**base, "status": "관심"}) == r"\[특별전\] \*빛\* · P · ~2026-12-31"
    assert label({**base, "status": "관람예정"}).endswith("관람예정일 2026-11-20")
    assert label({**base, "status": "관람완료"}).endswith("관람일 -")


def test_all_tab_is_one_line_list_and_loads_photos_only_when_opened(my_page):
    st_ = storage.LocalStorage(my_page)
    repository.add_photo(my_page, "1", st_.save_photo("a.jpg", photos.prepare_image(png())))
    at = open_done_tab(expand=False)
    all_tab = at.tabs[0]
    assert [e.label for e in all_tab.expander] == ["빛의 층위 · 관람일 2026-11-02 · 📷 1"]
    assert not all_tab.get("image")  # 접혀 있으면 사진을 불러오지 않는다
    at.session_state["all-1"] = True
    at.run()
    assert len(at.tabs[0].get("image")) == 1


def test_box_opened_in_one_status_tab_is_closed_after_moving_to_next_status(tmp_path, monkeypatch):
    """관심 탭에서 펼친 채 '관람예정'으로 바꿔도 관람예정 탭에서는 접힌 한 줄 목록으로 나온다."""
    db = str(tmp_path / "x.db")
    monkeypatch.setenv("DB_PATH", db)
    monkeypatch.setattr(config, "today_kst", lambda: TODAY)
    monkeypatch.setattr(culture_api, "fetch_exhibitions", lambda *a, **k: [EX])
    repository.init_db(db)
    repository.save(db, EX)
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.radio(key="page").set_value(messages.PAGE_MY).run()
    at.session_state["rec-관심-1"] = True
    at.session_state["rec-관심-open-1"] = True
    at.run()
    at.button(key="plan-1").click().run()
    assert not at.exception
    assert repository.list_by_status(db, "관람예정")
    assert not at.session_state["rec-관람예정-1"]  # 관람예정 탭의 상자는 접혀 있다
