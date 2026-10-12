"""Transparent ranking of a bounded, current API result set."""

from __future__ import annotations

import math

import typer

from catchtable_cli.client import CatchTableClient
from catchtable_cli.commands.common import (
    OutputFormat,
    fail,
    print_json,
    rows_output,
    run,
)
from catchtable_cli.dining import observed_at
from catchtable_cli.models import SearchShop
from catchtable_cli.requests import (
    region_request,
    resolve_region,
    search_body,
    search_request,
)
from catchtable_cli.validate import require_text, validate_date


def rank_shops(
    shops: list[dict],
    *,
    min_rating: float,
    min_reviews: int,
    available_only: bool,
    date: str | None,
    person_count: int | None,
    limit: int,
) -> list[dict]:
    items = []
    for raw in shops:
        shop = SearchShop.from_shop_result(raw)
        rating, count = shop.avg_rating, shop.review_count
        if (
            rating is None
            or count is None
            or rating < min_rating
            or count < min_reviews
        ):
            continue
        info = (shop.dining or {}).get("singleDateSlotInfo") or {}
        times = []
        # availableType can say AVAILABLE even when no slot fits the party.
        if (
            date
            and info.get("date") == date
            and info.get("personCount") == person_count
        ):
            for slot in info.get("timeSlotList") or []:
                if (
                    slot.get("availableYn") is True
                    and slot.get("personCount") == person_count
                ):
                    times.append(slot["time"])
        if available_only and not times:
            continue
        # A fixed, disclosed prior prevents one 5-star review dominating hundreds.
        score = (rating * count + 4.0 * 20) / (count + 20)
        item = shop.model_dump()
        item.pop("dining", None)
        item.update(
            {
                "score": round(score, 4),
                "available_times": sorted(set(times)),
                "availability_verified": bool(times),
                "reasons": [f"평점 {rating:.1f}, 리뷰 {count}개"]
                + (
                    [
                        f"{date} {person_count}명 가능 시간 {', '.join(sorted(set(times)))}"
                    ]
                    if times
                    else []
                ),
                "booking_url": f"https://app.catchtable.co.kr/ct/shop/{shop.shop_url or shop.shop_ref}",
            }
        )
        items.append(item)
    items.sort(key=lambda item: (item["score"], item["review_count"]), reverse=True)
    return items[:limit]


def recommend(
    region: str = typer.Option(..., "--region", "-r"),
    food_kind: str | None = typer.Option(
        None, "--food-kind", help="자동완성 FOOD_KIND의 code"
    ),
    date: str | None = typer.Option(None, "--date"),
    person_count: int | None = typer.Option(None, "--person-count", "-p", min=1),
    available_only: bool = typer.Option(
        False, "--available-only", help="해당 날짜·인원에 실제 시간 정보가 있는 후보만"
    ),
    min_rating: float = typer.Option(4.0, "--min-rating", min=0, max=5),
    min_reviews: int = typer.Option(20, "--min-reviews", min=0),
    limit: int = typer.Option(5, "--limit", "-n", min=1, max=20),
    candidates: int = typer.Option(
        30, "--candidates", min=1, max=100, help="한 페이지에서 검토할 후보 수"
    ),
    fmt: OutputFormat = typer.Option(OutputFormat.json, "--format", "-f"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """실제 검색 결과의 평점·리뷰·가능 시간을 근거로 후보를 추천합니다."""
    try:
        region = require_text(region, "region")
        if food_kind is not None:
            food_kind = require_text(food_kind, "food-kind")
        if date:
            validate_date(date)
        if bool(date) != (person_count is not None):
            raise ValueError("--date와 --person-count를 함께 사용하세요.")
        if available_only and not date:
            raise ValueError("--available-only에는 날짜와 인원이 필요합니다.")
        if not math.isfinite(min_rating):
            raise ValueError("min-rating은 유한한 숫자여야 합니다.")
    except ValueError as exc:
        fail(str(exc))

    def body(code):
        return search_body(
            code,
            date=date,
            person_count=person_count,
            food_kind=food_kind,
            size=candidates,
        )

    if dry_run:
        print_json(
            {
                "command": "recommend",
                "steps": [
                    region_request().plan(),
                    search_request(body("<region_code>")).plan(),
                ],
                "resolve": {"region_code": region},
                "ranking": "(rating*reviews + 4.0*20)/(reviews+20)",
            }
        )
        return

    async def execute():
        client = CatchTableClient()
        try:
            catalog = await region_request().send(client)
            try:
                code = resolve_region(catalog, region)
            except ValueError as exc:
                fail(str(exc))
            payload = await search_request(body(code)).send(client)
            data = payload.get("data") or {}
            shops = (data.get("shopResults") or {}).get("shops")
            if not isinstance(shops, list):
                raise RuntimeError("검색 응답에 매장 목록이 없습니다.")
            items = rank_shops(
                shops,
                min_rating=min_rating,
                min_reviews=min_reviews,
                available_only=available_only,
                date=date,
                person_count=person_count,
                limit=limit,
            )
            return {
                "ok": True,
                "observed_at": observed_at(),
                "region_code": code,
                "date": date,
                "person_count": person_count,
                "candidate_count": len(shops),
                "total_matches": data.get("totalShopCount"),
                "items": items,
                "ranking": {
                    "formula": "(rating*reviews + prior_rating*prior_reviews)/(reviews+prior_reviews)",
                    "prior_rating": 4.0,
                    "prior_reviews": 20,
                },
                "scope": "서버 별점 순 첫 페이지 내 추천. 전체 지역의 최적 식당이나 좌석 확보를 보장하지 않음.",
                "next_step": "선택한 매장은 shop availability 또는 reserve로 시간을 다시 확인하세요.",
            }
        finally:
            await client.close()

    output = run(execute())
    if fmt == OutputFormat.json:
        print_json(output)
    else:
        rows_output(
            output["items"],
            [
                "shop_name",
                "land_name",
                "avg_rating",
                "review_count",
                "available_times",
                "reasons",
            ],
            fmt,
            "추천 후보",
        )
