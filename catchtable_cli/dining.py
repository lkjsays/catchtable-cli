"""Read-only dining availability and official booking handoff."""

from __future__ import annotations

import base64
import json
from datetime import date as Date
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlencode

from cryptography.hazmat.primitives.asymmetric.padding import PKCS1v15
from cryptography.hazmat.primitives.serialization import (
    load_der_public_key,
    load_pem_public_key,
)

from catchtable_cli.models import ShopDetail
from catchtable_cli.requests import Request, shop_request
from catchtable_cli.validate import (
    positive_int,
    sanitize_identifier,
    validate_date,
)

ISSUE_KEY_PATH = "/api/reservation/v1/dining/issue-key"
TIME_SLOTS_PATH = "/api/reservation/v1/dining/time-slots"


def observed_at() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def booking_url(
    alias: str, date: str, person_count: int, service_time: str | None = None
) -> str:
    query = {
        "date": Date.fromisoformat(date).strftime("%y%m%d"),
        "personCount": person_count,
    }
    if service_time:
        query["time"] = service_time.replace(":", "")
    return f"https://app.catchtable.co.kr/ct/shop/{quote(sanitize_identifier(alias), safe='')}?{urlencode(query)}"


def time_slots_request(
    shop_ref: str,
    date: str,
    person_count: int,
    table_type: str,
    rsa: dict | None = None,
) -> Request:
    validate_date(date)
    positive_int(person_count, "person-count")
    plaintext = {
        "shopRef": shop_ref,
        "searchDate": date,
        "visitTime": "19:00",
        "personCount": person_count,
        "tableType": table_type,
    }
    if rsa is None:
        # Deferred inputs for dry-run; issuing a key is itself a network request.
        encrypted = "<RSA-PKCS1v15(JSON(encrypt_input)), from issue-key>"
        challenge = {k: f"<issue-key.data.rsa.{k}>" for k in ("c1", "c2", "c3", "c4")}
    else:
        key = rsa.get("slotEncPublicKey")
        if not isinstance(key, str) or not key:
            raise RuntimeError("시간 조회용 공개 키 응답이 없습니다.")
        try:
            public = (
                load_pem_public_key(key.encode())
                if "BEGIN" in key
                else load_der_public_key(base64.b64decode(key))
            )
            encrypted = base64.b64encode(
                public.encrypt(
                    json.dumps(plaintext, separators=(",", ":")).encode(), PKCS1v15()
                )
            ).decode()
            challenge = {k: rsa[k] for k in ("c1", "c2", "c3", "c4")}
        except (ValueError, TypeError, KeyError) as exc:
            raise RuntimeError("시간 조회용 키 응답 형식이 올바르지 않습니다.") from exc
    return Request(
        "POST",
        TIME_SLOTS_PATH,
        {
            "shopRef": shop_ref,
            "encryptedParamString": encrypted,
            "tableSeqs": None,
            **challenge,
        },
        {"shopRef": shop_ref},
    )


def availability_plan(
    alias: str, date: str, person_count: int, table_type: str
) -> dict:
    ref = "<shop_ref>"
    return {
        "command": "shop availability",
        "steps": [
            shop_request(alias).plan(),
            Request("GET", ISSUE_KEY_PATH).plan(),
            {
                **time_slots_request(ref, date, person_count, table_type).plan(),
                "encrypt_input": {
                    "shopRef": ref,
                    "searchDate": date,
                    "visitTime": "19:00",
                    "personCount": person_count,
                    "tableType": table_type,
                },
            },
        ],
    }


def normalize_times(
    payload: dict, *, date: str, person_count: int
) -> tuple[list[dict], dict]:
    data = payload.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("timeSlotMap"), dict):
        raise RuntimeError("시간 조회 응답에 timeSlotMap이 없습니다.")
    if data.get("state") not in (None, 200, "200"):
        raise RuntimeError(f"시간 조회 상태를 확인할 수 없습니다: {data.get('state')}")
    rows = []
    for key, raw in data["timeSlotMap"].items():
        if not isinstance(raw, dict) or len(key) != 4 or not key.isdigit():
            raise RuntimeError("시간 슬롯 응답 형식이 올바르지 않습니다.")
        hour, minute = int(key[:2]), int(key[2:])
        if hour >= 24 or minute >= 60:
            raise RuntimeError("시간 슬롯의 시간이 올바르지 않습니다.")
        period = raw.get("periodGubun")
        next_day = (period == "D" and hour < 12) or (period is None and hour < 6)
        day = Date.fromisoformat(date) + timedelta(days=int(next_day))
        actual = raw.get("availableYn")
        available = (
            actual if type(actual) is bool else {"Y": True, "N": False}.get(str(actual))
        )
        returned_count = raw.get("personCount", data.get("personCount"))
        # Mismatched dates/counts must not be offered as the user's requested slot.
        if raw.get("date") not in (
            None,
            Date.fromisoformat(date).strftime("%y%m%d"),
            date,
        ):
            raise RuntimeError("시간 조회 응답의 날짜가 요청과 다릅니다.")
        if returned_count is not None and returned_count != person_count:
            raise RuntimeError("시간 조회 응답의 인원이 요청과 다릅니다.")
        rows.append(
            {
                "date": day.isoformat(),
                "time": f"{hour:02}:{minute:02}",
                "service_time": f"{hour + 24 * int(next_day):02}:{minute:02}",
                "available": available,
                "person_count": person_count,
                "table_type": raw.get("tableType"),
                "confirmation_required": raw.get("isConfirmReservation"),
                "menu_set_seq": raw.get("menuSetSeq"),
            }
        )
    rows.sort(key=lambda r: (r["date"], r["time"]))
    return rows, {
        k: data.get(k)
        for k in (
            "state",
            "tablePersonMin",
            "tablePersonMax",
            "isLunchClosed",
            "isDinnerClosed",
        )
    }


async def availability(
    client, alias: str, date: str, person_count: int, table_type: str = "_ALL_"
) -> dict:
    raw = await shop_request(alias).send(client)
    data = raw.get("data")
    if not isinstance(data, dict) or not data:
        raise RuntimeError("매장 상세 응답이 없습니다.")
    vo = data.get("shopDetailVO", data)
    shop = ShopDetail.model_validate(vo)
    ref = shop.shop_ref
    if not ref:
        raise RuntimeError("매장 응답에 shopRef가 없습니다.")
    key_payload = await Request("GET", ISSUE_KEY_PATH).send(client)
    rsa = (key_payload.get("data") or {}).get("rsa")
    if not isinstance(rsa, dict):
        raise RuntimeError("시간 조회용 키를 발급받지 못했습니다.")
    payload = await time_slots_request(ref, date, person_count, table_type, rsa).send(
        client
    )
    rows, meta = normalize_times(payload, date=date, person_count=person_count)
    canonical_alias = (
        vo.get("urlPathAlias") or vo.get("catchtableUrlPath") or shop.shop_url or alias
    )
    return {
        "ok": True,
        "shop_ref": ref,
        "alias": canonical_alias,
        "shop_name": shop.shop_name,
        "service_date": date,
        "person_count": person_count,
        "observed_at": observed_at(),
        "availability_status": "available"
        if any(r["available"] is True for r in rows)
        else "unknown"
        if any(r["available"] is None for r in rows)
        else "unavailable",
        "slots": rows,
        "metadata": meta,
        "booking_url": booking_url(canonical_alias, date, person_count),
    }
