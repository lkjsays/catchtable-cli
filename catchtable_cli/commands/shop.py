"""Shop detail and day availability, including explicit partial failures."""

from __future__ import annotations

from typing import Any

import typer

from catchtable_cli.client import CatchTableClient
from catchtable_cli.commands.common import (
    OutputFormat,
    err_console,
    error_info,
    fail,
    field_names,
    print_json,
    rows_output,
    run,
    select,
)
from catchtable_cli.models import DaySlot, ShopDetail
from catchtable_cli.requests import shop_request, slots_request
from catchtable_cli.validate import (
    parse_params,
    positive_int,
    require_text,
    sanitize_identifier,
)

shop_app = typer.Typer(help="매장 정보")


def extract_slots(data: Any) -> list[dict]:
    if data is None:
        return []
    if isinstance(data, dict):
        for key in ("daySlots", "slots", "dates", "items"):
            if key in data:
                data = data[key]
                break
        else:
            raise RuntimeError("예약 날짜 응답에 날짜 목록이 없습니다.")
    if not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
        raise RuntimeError("예약 날짜 응답 형식이 올바르지 않습니다.")
    return data


@shop_app.command()
def info(
    alias: str = typer.Argument(help="매장 alias (예: bornandbredoriginal)"),
    fmt: OutputFormat = typer.Option(OutputFormat.json, "--format", "-f"),
    fields: str | None = typer.Option(
        None, "--fields", help="매장 필드 선택; 예약 날짜와 조회 상태는 유지"
    ),
    params_override: str | None = typer.Option(
        None, "--params", help="예약 날짜 조회 파라미터만 전달; shopRef 변경 불가"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="API 미호출, 의존 요청 계획 출력"
    ),
) -> None:
    """매장 상세와 날짜별 예약 상태를 조회합니다."""
    try:
        alias = sanitize_identifier(require_text(alias, "alias"), field_name="alias")
        names = field_names(fields, ShopDetail)
        params = parse_params(params_override)
        if "shopRef" in params:
            raise ValueError("--params로 shopRef를 변경할 수 없습니다.")
        if params.get("personCounts"):
            # The comma delimiter belongs to --params; one person count per call.
            try:
                positive_int(int(params["personCounts"]), "personCounts")
            except ValueError:
                raise ValueError("personCounts는 양의 정수여야 합니다.") from None
        request = shop_request(alias)
    except ValueError as exc:
        fail(str(exc))
    if dry_run:
        print_json(
            {
                "command": "shop info",
                "steps": [
                    request.plan(),
                    {
                        **slots_request("<shop_ref>", params).plan(),
                        "resolve": {
                            "shop_ref": "step1.data.shopDetailVO.shopRef (없으면 alias)"
                        },
                    },
                ],
            }
        )
        return

    async def execute():
        client = CatchTableClient()
        try:
            payload = await request.send(client)
            data = payload.get("data")
            if not isinstance(data, dict) or not data:
                raise RuntimeError("매장 상세 응답이 비어 있습니다.")
            shop = ShopDetail.model_validate(
                data.get("shopDetailVO", data.get("shop", data))
            )
            ref = shop.shop_ref or alias
            rows, errors, state = [], [], "empty"
            try:
                payload = await slots_request(ref, params).send(client)
                if "data" not in payload:
                    raise RuntimeError("예약 날짜 응답에 data가 없습니다.")
                for item in extract_slots(payload["data"]):
                    slot = DaySlot.model_validate(item)
                    value = slot.visit_yymmdd
                    if value and len(value) == 8 and value.isdigit():
                        slot.visit_yymmdd = f"{value[:4]}-{value[4:6]}-{value[6:]}"
                    rows.append(slot.model_dump())
                state = "ok" if rows else "empty"
            except Exception as exc:
                code, message = error_info(exc)
                state = "error"
                errors.append({"stage": "day_slots", "code": code, "message": message})
            return {
                "ok": not errors,
                "partial": bool(errors),
                "alias": alias,
                "shop_ref": ref,
                "shop": select(shop.model_dump(), names),
                "day_slots_status": state,
                "day_slots": rows,
                "errors": errors,
            }
        finally:
            await client.close()

    output = run(execute())
    if fmt == OutputFormat.json:
        print_json(output)
    else:
        rows_output(
            [output["shop"]],
            names or ["shop_name", "food_kind_name", "road_address", "avg_rating"],
            fmt,
            "매장 상세",
        )
        rows_output(
            output["day_slots"],
            ["visit_yymmdd", "status_code", "is_available", "available_person_counts"],
            fmt,
            "예약 날짜",
        )
        err_console.print(
            f"day_slots_status: {output['day_slots_status']}", markup=False
        )
    if output["partial"]:
        for error in output["errors"]:
            err_console.print(f"예약 날짜 조회 실패: {error['message']}", markup=False)
        raise typer.Exit(4)


@shop_app.command("availability")
def shop_availability(
    alias: str = typer.Argument(help="매장 alias 또는 shopRef"),
    date: str = typer.Option(..., "--date", help="영업일 YYYY-MM-DD"),
    person_count: int = typer.Option(..., "--person-count", "-p", min=1),
    table_type: str = typer.Option(
        "_ALL_", "--table-type", help="전체 _ALL_, 바 B, 홀 H 등"
    ),
    fmt: OutputFormat = typer.Option(OutputFormat.json, "--format", "-f"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """공식 시간 조회 API로 인원별 예약 가능한 시간을 확인합니다."""
    from catchtable_cli.dining import availability, availability_plan
    from catchtable_cli.validate import validate_date

    try:
        alias = sanitize_identifier(require_text(alias, "alias"))
        validate_date(date)
        table_type = sanitize_identifier(require_text(table_type, "table-type"))
    except ValueError as exc:
        fail(str(exc))
    if dry_run:
        print_json(availability_plan(alias, date, person_count, table_type))
        return

    async def execute():
        client = CatchTableClient()
        try:
            return await availability(client, alias, date, person_count, table_type)
        finally:
            await client.close()

    output = run(execute())
    if fmt == OutputFormat.json:
        print_json(output)
    else:
        rows_output(
            output["slots"],
            ["date", "time", "service_time", "available", "table_type"],
            fmt,
            f"{output['shop_name']} · {person_count}명",
        )
        err_console.print(
            f"availability_status: {output['availability_status']}\n{output['booking_url']}",
            markup=False,
        )


@shop_app.command("menu")
def shop_menu(
    alias: str = typer.Argument(help="매장 alias 또는 shopRef"),
    fmt: OutputFormat = typer.Option(OutputFormat.json, "--format", "-f"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """메뉴·가격·주류 필수 여부를 조회합니다. 안내용 가격은 미확인으로 구분합니다."""
    from catchtable_cli.dining import observed_at
    from catchtable_cli.requests import menu_request
    from catchtable_cli.shop_details import normalize_menu

    try:
        alias = sanitize_identifier(require_text(alias, "alias"))
        request = menu_request(alias)
    except ValueError as exc:
        fail(str(exc))
    if dry_run:
        print_json({"command": "shop menu", **request.plan()})
        return

    async def execute():
        client = CatchTableClient()
        try:
            return {
                "ok": True,
                "alias": alias,
                "observed_at": observed_at(),
                "source": request.url,
                **normalize_menu(await request.send(client)),
            }
        finally:
            await client.close()

    output = run(execute())
    if fmt == OutputFormat.json:
        print_json(output)
    else:
        rows_output(
            output["items"] + output["notices"],
            [
                "category",
                "name",
                "price_min",
                "price_max",
                "price_status",
                "description",
            ],
            fmt,
            "메뉴·가격",
        )
        err_console.print(
            f"price_status: {output['price_status']}\n주류 주문 필수: {output['alcohol_order_required']}\n{output['note']}",
            markup=False,
        )


@shop_app.command("policy")
def shop_policy(
    alias: str = typer.Argument(help="매장 alias 또는 shopRef"),
    date: str = typer.Option(..., "--date", help="실제 방문 날짜 YYYY-MM-DD"),
    time: str = typer.Option(..., "--time", help="실제 방문 시각 HH:MM (00~23시)"),
    person_count: int = typer.Option(..., "--person-count", "-p", min=1),
    table_type: str = typer.Option(
        "_ALL_", "--table-type", help="응답 좌석 필터: _ALL_, B, H 등"
    ),
    fmt: OutputFormat = typer.Option(OutputFormat.json, "--format", "-f"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """일반 예약금·캐치페이 0원 선택지·환불 규칙을 조회합니다. 좌석 확보/예약/결제는 하지 않습니다."""
    from catchtable_cli.dining import observed_at
    from catchtable_cli.requests import policy_request
    from catchtable_cli.shop_details import normalize_policy

    try:
        alias = sanitize_identifier(require_text(alias, "alias"))
        table_type = sanitize_identifier(require_text(table_type, "table-type"))
        deferred = policy_request("<shop_ref>", date, time, person_count)
    except ValueError as exc:
        fail(str(exc))
    if dry_run:
        print_json(
            {
                "command": "shop policy",
                "steps": [shop_request(alias).plan(), deferred.plan()],
                "table_type_filter": table_type,
                "creates_reservation": False,
            }
        )
        return

    async def execute():
        client = CatchTableClient()
        try:
            payload = await shop_request(alias).send(client)
            data = payload.get("data")
            if not isinstance(data, dict) or not data:
                raise RuntimeError("매장 상세 응답이 비어 있습니다.")
            shop = ShopDetail.model_validate(
                data.get("shopDetailVO", data.get("shop", data))
            )
            ref = shop.shop_ref or alias
            request = policy_request(ref, date, time, person_count)
            policy = normalize_policy(
                await request.send(client), person_count, table_type
            )
            return {
                "ok": policy["deposit_status"] != "unavailable",
                "alias": alias,
                "shop_ref": ref,
                "shop_name": shop.shop_name,
                "date": date,
                "time": time,
                "person_count": person_count,
                "observed_at": observed_at(),
                "source": request.plan(),
                **policy,
            }
        finally:
            await client.close()

    output = run(execute())
    if fmt == OutputFormat.json:
        print_json(output)
    else:
        rows_output(
            [output],
            [
                "shop_name",
                "date",
                "time",
                "person_count",
                "deposit_status",
                "base_deposit_total",
                "deposit_total",
            ],
            fmt,
            "예약 정책",
        )
        rows_output(
            output["table_options"],
            ["table_name", "reservable", "deposit_status", "base_deposit_total"],
            fmt,
            "좌석별 기본 예약금",
        )
        rows_output(
            output["refund_policies"],
            ["label", "refund_percent", "is_special_policy"],
            fmt,
            "환불 규칙",
        )
        rows_output(
            [output["zero_deposit_option"]],
            ["available", "upfront_amount", "requires_catchpay_card"],
            fmt,
            "캐치페이 예약금 0원 선택지",
        )
        err_console.print(output["zero_deposit_option"]["note"], markup=False)
        err_console.print(output["scope"], markup=False)
    if not output["ok"]:
        raise typer.Exit(5)
