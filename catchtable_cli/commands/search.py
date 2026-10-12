"""Search commands with shared request plans and normalized output."""

from __future__ import annotations

import typer

from catchtable_cli.client import CatchTableClient
from catchtable_cli.commands.common import (
    OutputFormat,
    err_console,
    fail,
    field_names,
    print_json,
    rows_output,
    run,
    select,
)
from catchtable_cli.models import AutocompleteData, AutocompleteSuggestion, SearchShop
from catchtable_cli.requests import (
    SORT_TYPES,
    autocomplete_request,
    region_request,
    resolve_region,
    search_body,
    search_request,
)
from catchtable_cli.validate import (
    parse_body,
    parse_params,
    positive_int,
    require_text,
    validate_date,
    validate_search_body,
)

search_app = typer.Typer(help="자동완성 및 지역 매장 검색")


async def _suggest(client: CatchTableClient, keyword: str) -> list[str]:
    # At most one optional request; do not reuse a closed client or event loop.
    if len(keyword) < 2:
        return []
    try:
        payload = await autocomplete_request({"query": keyword[:-1]}).send(client)
        return [
            s.label
            for s in AutocompleteData.model_validate(
                payload.get("data") or {}
            ).suggestions[:5]
            if s.label
        ]
    except Exception as exc:
        err_console.print(f"유사 키워드 조회 실패: {type(exc).__name__}", markup=False)
        return []


@search_app.command()
def search(
    keyword: str = typer.Argument(..., help="자동완성 키워드"),
    limit: int = typer.Option(
        20, "--limit", "-n", min=1, max=100, help="모든 형식의 items 최대 표시 건수"
    ),
    fmt: OutputFormat = typer.Option(OutputFormat.json, "--format", "-f"),
    fields: str | None = typer.Option(
        None, "--fields", help="쉼표 구분 정규화 필드 (label,item_type 등)"
    ),
    json_body: str | None = typer.Option(
        None, "--json-body", help="전체 요청 본문 대체 (query 문자열 필수)"
    ),
    params_override: str | None = typer.Option(
        None, "--params", help="HTTP 쿼리 파라미터 (key=value 쉼표 구분)"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="네트워크 없이 요청 계획 출력"
    ),
    suggest: bool = typer.Option(
        False, "--suggest", help="빈 결과일 때 접두어 제안 1회 조회"
    ),
) -> None:
    """자동완성 제안을 정규화해 조회합니다."""
    try:
        keyword = require_text(keyword, "keyword")
        body = parse_body(json_body) if json_body is not None else {"query": keyword}
        body["query"] = require_text(body.get("query"), "query")
        names = field_names(fields, AutocompleteSuggestion)
        request = autocomplete_request(body, parse_params(params_override))
    except ValueError as exc:
        fail(str(exc))
    if dry_run:
        print_json({"command": "search search", **request.plan(), "limit": limit})
        return

    async def execute():
        client = CatchTableClient()
        try:
            payload = await request.send(client)
            raw = payload.get("data")
            if not isinstance(raw, dict) or not any(
                isinstance(raw.get(k), list) for k in ("suggestions", "items", "list")
            ):
                raise RuntimeError("자동완성 응답에 제안 목록이 없습니다.")
            data = AutocompleteData.model_validate(raw)
            rows = [
                select(item.model_dump(), names) for item in data.suggestions[:limit]
            ]
            hints = (
                await _suggest(client, body["query"]) if not rows and suggest else []
            )
            return {
                "ok": True,
                "items": rows,
                "total": len(data.suggestions),
                "returned": len(rows),
                "suggestions": hints,
            }
        finally:
            await client.close()

    output = run(execute())
    if fmt == OutputFormat.json:
        print_json(output)
    else:
        rows_output(
            output["items"],
            names or ["item_type", "label", "matching_count"],
            fmt,
            "자동완성 결과",
        )
        if output["suggestions"]:
            err_console.print(", ".join(output["suggestions"]), markup=False)


@search_app.command()
def region(
    region_name: str = typer.Option(
        ..., "--region", "-r", help="정확한 지역명 또는 코드 (강남, 부산, CAT026)"
    ),
    visit_date: str | None = typer.Option(
        None,
        "--visit-date",
        "-d",
        help="예약 정보 조회일 YYYY-MM-DD (매장 제외 필터 아님)",
    ),
    person_count: int | None = typer.Option(
        None, "--person-count", "-p", min=1, help="예약 정보 조회 인원 (방문일 필수)"
    ),
    sort: str = typer.Option(
        "RATING", "--sort", "-s", help="RATING, REVIEW, RECOMMENDED; DISTANCE 미지원"
    ),
    food_kind: str | None = typer.Option(
        None, "--food-kind", help="자동완성 FOOD_KIND의 code (예: E_31)"
    ),
    cursor: str = typer.Option(
        "0", "--cursor", help="첫 조회는 0, 이후 응답의 next_cursor 사용"
    ),
    page_size: int = typer.Option(15, "--page-size", min=1, max=100),
    fmt: OutputFormat = typer.Option(OutputFormat.json, "--format", "-f"),
    fields: str | None = typer.Option(
        None, "--fields", help="정규화 매장 필드 선택 (모든 출력 형식)"
    ),
    json_body: str | None = typer.Option(
        None, "--json-body", help="전체 검색 본문 대체, 지역 해석 생략"
    ),
    params_override: str | None = typer.Option(
        None, "--params", help="검색 요청의 HTTP 쿼리 파라미터"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="지역 조회와 검색의 의존 요청 계획 출력"
    ),
) -> None:
    """지역 코드 기반으로 매장과 예약 정보를 조회합니다."""
    try:
        region_name = require_text(region_name, "region")
        if visit_date is not None:
            validate_date(visit_date)
        if person_count is not None:
            positive_int(person_count, "person-count")
            if visit_date is None:
                raise ValueError("--person-count는 --visit-date와 함께 사용하세요.")
        if sort not in SORT_TYPES:
            raise ValueError(
                "지원하는 정렬: RATING, REVIEW, RECOMMENDED. DISTANCE는 기준 좌표가 없어 미지원입니다."
            )
        if food_kind is not None:
            food_kind = require_text(food_kind, "food-kind")
        cursor = require_text(cursor, "cursor")
        names = field_names(fields, SearchShop)
        params = parse_params(params_override)
        raw_body = parse_body(json_body) if json_body is not None else None

        def build(code: str):
            return (
                raw_body
                if raw_body is not None
                else search_body(
                    code,
                    date=visit_date,
                    person_count=person_count,
                    food_kind=food_kind,
                    sort=sort,
                    cursor=cursor,
                    size=page_size,
                )
            )

        validate_search_body(build("<resolved_region_code>"))
    except ValueError as exc:
        fail(str(exc))
    if dry_run:
        steps = (
            []
            if raw_body is not None
            else [
                {
                    **region_request().plan(),
                    "resolve": {
                        "name": region_name,
                        "match": "ctRegions name/displayName/code (정확히 하나)",
                        "output": "<resolved_region_code>",
                    },
                }
            ]
        )
        steps.append(search_request(build("<resolved_region_code>"), params).plan())
        print_json({"command": "search region", "steps": steps})
        return

    async def execute():
        client = CatchTableClient()
        try:
            code = None
            if raw_body is None:
                catalog = await region_request().send(client)
                try:
                    code = resolve_region(catalog, region_name)
                except ValueError as exc:
                    fail(str(exc))
            request = search_request(build(code), params)
            payload = await request.send(client)
            data = payload.get("data")
            if not isinstance(data, dict) or not isinstance(
                data.get("shopResults"), dict
            ):
                raise RuntimeError("검색 응답에 shopResults가 없습니다.")
            shops = data["shopResults"].get("shops")
            if not isinstance(shops, list):
                raise RuntimeError("검색 응답에 매장 목록이 없습니다.")
            rows = [
                select(SearchShop.from_shop_result(s).model_dump(), names)
                for s in shops
            ]
            paging = data.get("paging") or {}
            return {
                "ok": True,
                "region_code": code,
                "total": data.get("totalShopCount"),
                "returned": len(rows),
                "next_cursor": paging.get("nextOffset")
                if paging.get("hasMore")
                else None,
                "items": rows,
            }
        finally:
            await client.close()

    output = run(execute())
    if fmt == OutputFormat.json:
        print_json(output)
    else:
        columns = names or [
            "shop_name",
            "food_kind_name",
            "land_name",
            "avg_rating",
            "review_count",
        ]
        if visit_date and not names:
            columns += ["dining"]
        rows_output(output["items"], columns, fmt, f"검색 결과: {region_name}")
        if output["next_cursor"]:
            err_console.print(f"next_cursor: {output['next_cursor']}", markup=False)


@search_app.command("keyword")
def keyword_search(
    keyword: str = typer.Argument(help="식당명 또는 검색어"),
    region_name: str | None = typer.Option(None, "--region", "-r"),
    page_size: int = typer.Option(15, "--page-size", min=1, max=100),
    cursor: str = typer.Option("0", "--cursor"),
    fmt: OutputFormat = typer.Option(OutputFormat.json, "--format", "-f"),
    fields: str | None = typer.Option(None, "--fields"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """자동완성 대신 실제 매장 목록을 식당명·키워드로 검색합니다."""
    try:
        keyword = require_text(keyword, "keyword")
        if region_name is not None:
            region_name = require_text(region_name, "region")
        cursor = require_text(cursor, "cursor")
        names = field_names(fields, SearchShop)
    except ValueError as exc:
        fail(str(exc))

    def build(code):
        body = search_body(
            code or "", sort="RECOMMENDED", cursor=cursor, size=page_size
        )
        if not code:
            body["filters"].pop("displayRegionCodes")
        body["keywordSearch"] = {"keyword": keyword}
        return body

    if dry_run:
        steps = [region_request().plan()] if region_name else []
        steps.append(
            search_request(build("<region_code>" if region_name else None)).plan()
        )
        print_json(
            {"command": "search keyword", "steps": steps, "resolve_region": region_name}
        )
        return

    async def execute():
        client = CatchTableClient()
        try:
            code = None
            if region_name:
                catalog = await region_request().send(client)
                try:
                    code = resolve_region(catalog, region_name)
                except ValueError as exc:
                    fail(str(exc))
            payload = await search_request(build(code)).send(client)
            data = payload.get("data") or {}
            shops = (data.get("shopResults") or {}).get("shops")
            if not isinstance(shops, list):
                raise RuntimeError("검색 응답에 매장 목록이 없습니다.")
            paging = data.get("paging") or {}
            return {
                "ok": True,
                "region_code": code,
                "total": data.get("totalShopCount"),
                "returned": len(shops),
                "next_cursor": paging.get("nextOffset")
                if paging.get("hasMore")
                else None,
                "items": [
                    select(SearchShop.from_shop_result(shop).model_dump(), names)
                    for shop in shops
                ],
            }
        finally:
            await client.close()

    output = run(execute())
    if fmt == OutputFormat.json:
        print_json(output)
    else:
        rows_output(
            output["items"],
            names
            or ["shop_name", "shop_url", "food_kind_name", "land_name", "avg_rating"],
            fmt,
            keyword,
        )
        if output["next_cursor"]:
            err_console.print(f"next_cursor: {output['next_cursor']}", markup=False)
