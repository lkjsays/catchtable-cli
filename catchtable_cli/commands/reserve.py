"""Verify a requested slot and hand off to the official booking flow."""

from __future__ import annotations

import typer

from catchtable_cli.client import CatchTableClient
from catchtable_cli.commands.common import fail, print_json, run
from catchtable_cli.dining import availability, availability_plan, booking_url
from catchtable_cli.validate import (
    require_text,
    sanitize_identifier,
    validate_date,
    validate_time,
)


def reserve(
    alias: str = typer.Argument(help="매장 alias 또는 shopRef"),
    date: str = typer.Option(..., "--date", help="영업일 YYYY-MM-DD"),
    time: str = typer.Option(..., "--time", help="availability의 service_time (HH:MM)"),
    person_count: int = typer.Option(..., "--person-count", "-p", min=1),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """최신 시간을 확인하고 공식 예약 화면으로 연결합니다. 예약을 생성하지 않습니다."""
    try:
        alias = sanitize_identifier(require_text(alias, "alias"))
        validate_date(date)
        validate_time(time)
    except ValueError as exc:
        fail(str(exc))
    if dry_run:
        print_json(
            {
                **availability_plan(alias, date, person_count, "_ALL_"),
                "command": "reserve",
                "select_service_time": time,
                "creates_reservation": False,
                "next_step": "공식 화면에서 로그인·메뉴·보증금·취소 조건 확인 후 예약 확정",
            }
        )
        return

    async def execute():
        client = CatchTableClient()
        try:
            output = await availability(client, alias, date, person_count)
            slots = [
                slot
                for slot in output["slots"]
                if slot["service_time"] == time and slot["available"] is True
            ]
            return {
                "ok": bool(slots),
                "status": "ready_for_browser" if slots else "slot_unavailable",
                "reservation_created": False,
                "shop_name": output["shop_name"],
                "shop_ref": output["shop_ref"],
                "service_date": date,
                "service_time": time,
                "person_count": person_count,
                "observed_at": output["observed_at"],
                "slots": slots,
                "booking_url": booking_url(output["alias"], date, person_count, time)
                if slots
                else None,
                "next_action": "공식 화면에서 로그인 후 메뉴·예약금·취소 조건을 확인하고 예약하세요."
                if slots
                else "선택한 시간은 현재 확인되지 않습니다. shop availability로 다른 시간을 확인하세요.",
                "completion_evidence": "공식 예약 완료 화면 또는 reservations list의 예약 내역",
            }
        finally:
            await client.close()

    output = run(execute())
    print_json(output)
    if not output["ok"]:
        raise typer.Exit(5)
