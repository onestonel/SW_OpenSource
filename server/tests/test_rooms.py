"""정산방 · 구성원 API (#9). 완료 기준: /docs 에서 정산방을 만들고 다시 조회할 수 있다."""

from __future__ import annotations

import pytest

from tests.conftest import error


def make(api, members=("A", "B", "C", "D"), **over) -> dict:
    return api.post("/rooms", {"name": "제주 여행", "members": list(members), **over}).json()


# ------------------------------------------------------------------ 만들기 · 다시 조회

def test_create_and_reopen_by_link(api):
    room = make(api)
    assert room["name"] == "제주 여행" and room["rounding"] == "WON_1"  # 기본 1원 단위
    assert len(room["room_token"]) >= 22  # 추측하기 어려운 키 (128비트)
    assert room["members"] == [{"id": room["members"][i]["id"], "name": n, "order": i + 1}
                               for i, n in enumerate("ABCD")]
    assert room["created_at"].endswith("+09:00")  # 한국 시간

    again = api.get(f"/rooms/{room['room_token']}").json()
    assert again == {**room, "latest_settlement": None}


def test_tokens_are_unique(api):
    tokens = {make(api, ("A", "B"))["room_token"] for _ in range(5)}
    assert len(tokens) == 5


def test_rounding_option(api):
    assert make(api, ("A", "B"), rounding="WON_10")["rounding"] == "WON_10"


def test_member_names_are_trimmed(api):
    assert [m["name"] for m in make(api, ("  A ", "B"))["members"]] == ["A", "B"]


@pytest.mark.parametrize(("members", "reason"), [
    ([], "2개 이상이어야 합니다"),
    (["A"], "2개 이상이어야 합니다"),
    (["A", "A"], "같은 이름이 있습니다: A"),
])
def test_member_count_and_duplicates(api, members, reason):
    res = api.post("/rooms", {"name": "x", "members": members}, expect=422)
    assert error(res) == {"code": "VALIDATION_ERROR", "message": "입력값을 확인해 주세요.",
                          "details": {"fields": {"members": reason}}}


@pytest.mark.parametrize(("members", "field", "reason"), [
    (["A", ""], "members.1", "빈 값은 안 됩니다"),
    (["A", "   "], "members.1", "빈 값은 안 됩니다"),
    (["A", "가" * 21], "members.1", "20자 이하여야 합니다"),
])
def test_blank_or_long_member_name(api, members, field, reason):
    res = api.post("/rooms", {"name": "x", "members": members}, expect=422)
    assert error(res)["details"]["fields"] == {field: reason}


def test_required_fields_and_rounding_values(api):
    res = api.post("/rooms", {}, expect=422)
    assert error(res)["details"]["fields"] == {"name": "필수", "members": "필수"}
    res = api.post("/rooms", {"name": "x", "members": ["A", "B"], "rounding": "WON_100"}, expect=422)
    assert error(res)["details"]["fields"] == {"rounding": "'WON_1' 또는 'WON_10' 중 하나여야 합니다"}


def test_wrong_link_is_not_found(api):
    room = make(api)
    for url in ["/rooms/wrong-token", "/rooms/1"]:  # 틀린 키, 숫자 id 모두 404
        res = api.get(url, expect=404)
        assert error(res) == {"code": "NOT_FOUND", "message": "정산방을 찾을 수 없습니다. 링크를 확인해 주세요."}
    assert api.get(f"/rooms/{room['room_token']}").status_code == 200


# ------------------------------------------------------------------ 바꾸기

def test_update_name_and_rounding(api):
    token = make(api)["room_token"]
    room = api.patch(f"/rooms/{token}", {"rounding": "WON_10"}).json()
    assert room["rounding"] == "WON_10" and room["name"] == "제주 여행"
    room = api.patch(f"/rooms/{token}", {"name": "제주 2박 3일"}).json()
    assert room["name"] == "제주 2박 3일" and room["rounding"] == "WON_10"
    assert api.get(f"/rooms/{token}").json()["name"] == "제주 2박 3일"


# ------------------------------------------------------------------ 구성원

def test_add_member(api):
    token = make(api)["room_token"]
    e = api.post(f"/rooms/{token}/members", {"name": "E"}).json()
    assert e["name"] == "E" and e["order"] == 5
    assert [m["name"] for m in api.get(f"/rooms/{token}").json()["members"]] == list("ABCDE")

    res = api.post(f"/rooms/{token}/members", {"name": "A"}, expect=409)
    assert error(res)["code"] == "MEMBER_NAME_DUPLICATE"
    res = api.post(f"/rooms/{token}/members", {"name": " "}, expect=422)
    assert error(res)["details"]["fields"] == {"name": "빈 값은 안 됩니다"}


def test_delete_member(api):
    room = make(api, ("A", "B", "C"))
    token, (a, b, _) = room["room_token"], (m["id"] for m in room["members"])
    api.delete(f"/rooms/{token}/members/{b}")
    assert [m["name"] for m in api.get(f"/rooms/{token}").json()["members"]] == ["A", "C"]

    res = api.delete(f"/rooms/{token}/members/{a}", expect=409)  # 2명 미만이 되면 안 된다
    assert error(res)["code"] == "MEMBERS_TOO_FEW"
    api.delete(f"/rooms/{token}/members/{b}", expect=404)  # 이미 지움


def test_member_of_other_room_is_not_found(api):
    mine = make(api)["room_token"]
    other_member = make(api, ("X", "Y", "Z"))["members"][0]["id"]
    api.delete(f"/rooms/{mine}/members/{other_member}", expect=404)


def test_docs_lists_room_api(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert {"/api/v1/rooms", "/api/v1/rooms/{room_token}", "/api/v1/rooms/{room_token}/members",
            "/api/v1/rooms/{room_token}/members/{member_id}"} <= set(paths)
