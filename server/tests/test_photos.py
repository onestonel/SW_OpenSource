"""완료 기준: 사진을 올리면 무작위 이름으로 저장되고, 주소로 다시 볼 수 있다."""

from __future__ import annotations

import pytest

from app import storage

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 32


@pytest.fixture(autouse=True)
def tmp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "storage_dir", lambda: tmp_path)
    return tmp_path


def upload(client, data: bytes, filename: str = "내영수증.png", content_type: str = "image/png"):
    return client.post("/api/v1/receipt-photos", files={"file": (filename, data, content_type)})


@pytest.mark.parametrize("data,ext", [(PNG, ".png"), (JPG, ".jpg")])
def test_upload_then_view(client, tmp_storage, data, ext):
    res = upload(client, data)
    assert res.status_code == 200
    url = res.json()["photo_url"]
    name = url.rsplit("/", 1)[1]

    # 사용자가 보낸 이름이 아니라 무작위 이름으로 저장된다
    assert name.endswith(ext) and "내영수증" not in name
    assert (tmp_storage / name).read_bytes() == data

    got = client.get(url)
    assert got.status_code == 200
    assert got.content == data


def test_names_are_random(client):
    assert upload(client, PNG).json() != upload(client, PNG).json()


def test_too_large(client, tmp_storage):
    res = upload(client, PNG + b"\x00" * storage.MAX_BYTES)
    assert res.status_code == 413
    assert res.json()["error"]["code"] == "FILE_TOO_LARGE"
    assert list(tmp_storage.iterdir()) == []


def test_not_an_image(client):
    # Content-Type을 image/png로 속여도 내용이 사진이 아니면 거절한다
    res = upload(client, b"hello", filename="a.png")
    assert res.status_code == 415
    assert res.json()["error"]["code"] == "UNSUPPORTED_MEDIA_TYPE"


@pytest.mark.parametrize("name", ["0" * 32 + ".png", "..%2Fapp%2Fmain.py", "abc.txt"])
def test_missing_or_bad_name(client, name):
    res = client.get(f"/api/v1/receipt-photos/{name}")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "NOT_FOUND"
