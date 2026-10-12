"""Pure request builders shared by execution and network-free previews."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from catchtable_cli.validate import sanitize_identifier

REGIONS_PATH = "/api/v4/filters/ct-region-filter"
SEARCH_PATH = "/api/v7/search/list"
SORT_TYPES = {
    "RATING": "avg_score",
    "REVIEW": "review_count",
    "RECOMMENDED": "recommended",
}


@dataclass
class Request:
    method: str
    url: str
    body: dict[str, Any] | None = None
    params: dict[str, str] | None = None

    def plan(self) -> dict[str, Any]:
        return asdict(self)

    async def send(self, client: Any) -> dict[str, Any]:
        return await client._request(
            self.method, self.url, json_body=self.body, params=self.params
        )


def autocomplete_request(body: dict, params: dict | None = None) -> Request:
    return Request("POST", "/api/v5/autocomplete/_list", body, params or None)


def region_request() -> Request:
    return Request("GET", REGIONS_PATH)


def resolve_region(payload: dict, name: str) -> str:
    nodes = payload.get("data", {}).get("ctRegions")
    if not isinstance(nodes, list) or not nodes:
        raise RuntimeError("지역 목록 응답 형식이 올바르지 않습니다.")
    matches: set[str] = set()

    def visit(items: list) -> None:
        for item in items:
            if item.get("code") and name in (
                item.get("name"),
                item.get("displayName"),
                item.get("code"),
            ):
                matches.add(item["code"])
            visit(item.get("children", []))

    visit(nodes)
    if len(matches) != 1:
        raise ValueError(
            f"지역 {name!r}을 하나의 지역 코드로 확정할 수 없습니다. 정확한 지역명 또는 지역 코드를 사용하세요."
        )
    return matches.pop()


def search_body(
    region_code: str,
    *,
    date: str | None = None,
    person_count: int | None = None,
    food_kind: str | None = None,
    sort: str = "RATING",
    cursor: str = "0",
    size: int = 15,
) -> dict:
    filters: dict[str, Any] = {"displayRegionCodes": [region_code]}
    if food_kind:
        filters["foodKindCodes"] = [food_kind]
    reservation = {}
    if date:
        reservation["reservationDate"] = date
    if person_count is not None:
        reservation["personCount"] = person_count
    return {
        "paging": {"offset": cursor, "size": size},
        "filters": filters,
        "sort": {"sortType": SORT_TYPES[sort]},
        "reservationParams": reservation,
        "listType": "GENERAL",
        "divideType": "NON_DIVIDE",
    }


def search_request(body: dict, params: dict | None = None) -> Request:
    return Request("POST", SEARCH_PATH, body, params or None)


def shop_request(alias: str) -> Request:
    return Request("GET", f"/api/v4/shops/{sanitize_identifier(alias)}")


def menu_request(alias: str) -> Request:
    return Request(
        "GET", f"/api/display/v2/shops/{sanitize_identifier(alias)}/tabs/menu"
    )


def policy_request(shop_ref: str, date: str, time: str, person_count: int) -> Request:
    from datetime import date as Date

    from catchtable_cli.validate import positive_int, validate_date, validate_time

    validate_date(date)
    validate_time(time)
    positive_int(person_count, "person-count")
    if int(time[:2]) >= 24:
        raise ValueError("예약 정책은 실제 방문 날짜와 00:00~23:59 시간을 사용하세요.")
    return Request(
        "GET",
        "/api/reservation/v1/dining/reservation-options",
        params={
            "shopRef": shop_ref,
            "date": Date.fromisoformat(date).strftime("%y%m%d"),
            "time": time.replace(":", ""),
            "personCount": str(person_count),
        },
    )


def slots_request(shop_ref: str, params: dict | None = None) -> Request:
    return Request(
        "GET",
        "/api/reservation/v1/dining/day-slots",
        params={
            "tableSeqs": "",
            "personCounts": "",
            **(params or {}),
            "shopRef": shop_ref,
        },
    )
