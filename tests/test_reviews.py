import pytest

from exhibition_app import messages, repository as repo


def ex(i="1"):
    return {"exhibition_id": i, "title": "전시", "category": "미술", "region": "서울",
            "place": "미술관", "start_date": "2026-11-01", "end_date": "2026-12-01"}


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "x.db")
    assert repo.init_db(path).ok
    assert repo.save(path, ex("1")).ok
    return path


def row(db):
    return [r for st in repo.STATUSES for r in repo.list_by_status(db, st)][0]


def complete(db):
    assert repo.plan(db, "1", "2026-11-10").ok
    assert repo.complete(db, "1").ok


def rejects(db, fn, msg):
    before = row(db)
    res = fn()
    assert not res.ok and res.message == msg
    assert row(db) == before


def test_ac10_cannot_write_before_completed(db):
    rejects(db, lambda: repo.write_review(db, "1", 4, "좋음"), messages.REVIEW_STATE)
    assert repo.plan(db, "1", "2026-11-10").ok
    rejects(db, lambda: repo.write_review(db, "1", 4, "좋음"), messages.REVIEW_STATE)
    rejects(db, lambda: repo.delete_review(db, "1"), messages.REVIEW_STATE)


@pytest.mark.parametrize("rating", [0, 6, 3.5, -1, "3", None, True])
def test_ac10_bad_rating_rejected(db, rating):
    complete(db)
    rejects(db, lambda: repo.write_review(db, "1", rating, "좋음"), messages.INVALID_RATING)


@pytest.mark.parametrize("text", ["", "   \n\t ", "가" * 1001, " " + "가" * 1001 + " ", None, 5])
def test_ac10_bad_text_rejected(db, text):
    complete(db)
    rejects(db, lambda: repo.write_review(db, "1", 3, text), messages.INVALID_REVIEW_TEXT)


def test_ac10_write_edit_and_limits(db):
    complete(db)
    assert repo.write_review(db, "1", 5, "  멋짐  ").ok
    r = row(db)
    assert (r["review_rating"], r["review_text"], r["status"]) == (5, "멋짐", "관람완료")
    assert repo.write_review(db, "1", 1, "가" * 1000).ok
    r = row(db)
    assert r["review_rating"] == 1 and len(r["review_text"]) == 1000
    assert r["planned_visit_date"] == "2026-11-10"


def test_ac10_bad_edit_keeps_existing_review(db):
    complete(db)
    assert repo.write_review(db, "1", 4, "기존").ok
    rejects(db, lambda: repo.write_review(db, "1", 9, "새"), messages.INVALID_RATING)
    assert row(db)["review_text"] == "기존"


def test_ac10_delete_review_keeps_row(db):
    complete(db)
    assert repo.write_review(db, "1", 4, "기존").ok
    assert repo.delete_review(db, "1").ok
    r = row(db)
    assert r["status"] == "관람완료" and r["review_rating"] is None and r["review_text"] is None
    assert repo.count(db) == 1 and len(repo.list_by_status(db, "관람완료")) == 1
