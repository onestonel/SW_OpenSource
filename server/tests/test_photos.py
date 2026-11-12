"""영수증 사진 (API 명세서 3절 「사진」). 올리기 · 보기 · 다시 올리기 · 영수증 지울 때 같이 지우기."""

from __future__ import annotations

import pytest

from app import storage
from tests.conftest import error

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 32


@pytest.fixture(autouse=True)
def tmp_storage(tmp_path, monkeypatch):
    """사진을 진짜 폴더 대신 테스트용 임시 폴더에 저장한다."""
    monkeypatch.setattr(storage, "storage_dir", lambda: tmp_path)
    return tmp_path


@pytest.fixture
def room(api) -> dict:
    return api.post("/rooms", {"name": "제주 여행", "members": ["A", "B"]}).json()


def make_receipt(api, room) -> dict:
    body = {
        "store_name": "1차 식당",
        "payer_member_id": room["members"][0]["id"],
        "total_amount": 10000,
        "items": [{"name": "김치찌개", "amount": 10000}],
    }
    return api.post(f"/rooms/{room['room_token']}/receipts", body).json()


def photo_url(room, receipt) -> str:
    return f"/api/v1/rooms/{room['room_token']}/receipts/{receipt['id']}/photo"


def upload(client, url, data: bytes):
    return client.post(url, files={"file": ("내영수증.png", data, "image/png")})


def saved_files(folder) -> list[str]:
    return sorted(p.name for p in folder.iterdir())


# ------------------------------------------------------------------ 올리기 · 보기

@pytest.mark.parametrize(("data", "ext"), [(PNG, ".png"), (JPG, ".jpg")])
def test_upload_then_view(api, client, room, tmp_storage, data, ext):
    receipt = make_receipt(api, room)
    url = photo_url(room, receipt)

    res = upload(client, url, data)
    assert res.status_code == 200
    assert res.json() == {"photo_url": url}

    # 사용자가 보낸 이름이 아니라 무작위 이름으로 저장된다
    [name] = saved_files(tmp_storage)
    assert name.endswith(ext) and "내영수증" not in name

    got = client.get(url)
    assert got.status_code == 200 and got.content == data

    # 영수증 보기에도 사진 주소가 나온다
    assert api.get(f"/rooms/{room['room_token']}/receipts/{receipt['id']}").json()["photo_url"] == url


def test_upload_again_replaces_old_file(api, client, room, tmp_storage):
    receipt = make_receipt(api, room)
    url = photo_url(room, receipt)
    upload(client, url, PNG)
    [first] = saved_files(tmp_storage)

    upload(client, url, JPG)
    [second] = saved_files(tmp_storage)  # 파일은 하나만 남는다
    assert second != first and second.endswith(".jpg")
    assert client.get(url).content == JPG


def test_deleting_receipt_deletes_photo(api, client, room, tmp_storage):
    receipt = make_receipt(api, room)
    upload(client, photo_url(room, receipt), PNG)
    assert len(saved_files(tmp_storage)) == 1

    api.delete(f"/rooms/{room['room_token']}/receipts/{receipt['id']}")
    assert saved_files(tmp_storage) == []


# ------------------------------------------------------------------ 오류 경우

def test_too_large(api, client, room, tmp_storage):
    url = photo_url(room, make_receipt(api, room))
    res = upload(client, url, PNG + b"\x00" * storage.MAX_BYTES)
    assert res.status_code == 413 and error(res)["code"] == "FILE_TOO_LARGE"
    assert saved_files(tmp_storage) == []


def test_not_an_image(api, client, room):
    # Content-Type을 image/png로 속여도 내용이 사진이 아니면 거절한다
    res = upload(client, photo_url(room, make_receipt(api, room)), b"hello")
    assert res.status_code == 415 and error(res)["code"] == "UNSUPPORTED_MEDIA_TYPE"


def test_confirmed_receipt_cannot_change_photo(api, client, room, tmp_storage):
    receipt = make_receipt(api, room)
    api.post(f"/rooms/{room['room_token']}/receipts/{receipt['id']}/confirm", expect=200)
    res = upload(client, photo_url(room, receipt), PNG)
    assert res.status_code == 409 and error(res)["code"] == "RECEIPT_CONFIRMED"
    assert saved_files(tmp_storage) == []


def test_no_photo_yet(api, client, room):
    res = client.get(photo_url(room, make_receipt(api, room)))
    assert res.status_code == 404 and error(res)["code"] == "NOT_FOUND"


def test_receipt_of_other_room(api, client, room):
    other = api.post("/rooms", {"name": "다른 방", "members": ["X", "Y"]}).json()
    receipt = make_receipt(api, other)
    upload(client, photo_url(other, receipt), PNG)

    wrong = f"/api/v1/rooms/{room['room_token']}/receipts/{receipt['id']}/photo"  # 내 정산방 주소로 남의 영수증
    assert client.get(wrong).status_code == 404
    assert upload(client, wrong, PNG).status_code == 404