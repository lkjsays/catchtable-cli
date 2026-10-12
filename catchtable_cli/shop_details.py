"""Public menu and slot-specific reservation policy; never creates a holding."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation


def amount(value) -> int | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value).replace(",", ""))
        if not number.is_finite() or number < 0 or number != number.to_integral_value():
            return None
        return int(number)
    except (InvalidOperation, ValueError):
        return None


def normalize_menu(payload: dict) -> dict:
    data = payload.get("data", payload)
    if not isinstance(data, dict) or not isinstance(data.get("menus"), list):
        raise RuntimeError("메뉴 응답에 menus 목록이 없습니다.")
    items, notices = [], []

    def visit(nodes, category=None):
        if not isinstance(nodes, list):
            raise RuntimeError("메뉴 항목 형식이 올바르지 않습니다.")
        for raw in nodes:
            if not isinstance(raw, dict):
                raise RuntimeError("메뉴 항목 형식이 올바르지 않습니다.")
            if raw.get("type") == "category":
                visit(raw.get("items"), raw.get("name"))
                continue
            name = str(raw.get("name") or "")
            description = str(raw.get("description") or "")
            low, high = amount(raw.get("minPrice")), amount(raw.get("maxPrice"))
            notice = bool(re.search(r"(?:참조|참고|확인|문의|공지|안내)", name))
            # Values such as 0/1 are often administrative placeholders, not prices.
            status = (
                "notice"
                if notice
                else "unknown"
                if low is None or low <= 1 or (high is not None and high < low)
                else "listed"
            )
            row = {
                "menu_id": raw.get("foodMenuSeq"),
                "category": category,
                "name": name,
                "description": description,
                "price_min": low if status == "listed" else None,
                "price_max": (high if high is not None else low)
                if status == "listed"
                else None,
                "price_status": status,
                "source_price_min": raw.get("minPrice"),
                "source_price_max": raw.get("maxPrice"),
                "representative": raw.get("isRepresentative"),
                "image_url": raw.get("imageUrl"),
            }
            (notices if notice else items).append(row)

    visit(data["menus"])
    details = data.get("menuDetailInfo") or {}
    if not isinstance(details, dict):
        raise RuntimeError("메뉴 안내 응답 형식이 올바르지 않습니다.")
    return {
        "items": items,
        "notices": notices,
        "menu_boards": data.get("menuBoards", []),
        "last_updated_at": details.get("lastMenuUpdateDateTime"),
        "alcohol_order_required": details.get("isAlcoholOrderRequired"),
        "corkage_guide": details.get("corkChargeGuide"),
        "price_status": "listed"
        if any(i["price_status"] == "listed" for i in items)
        else "unknown",
        "currency": "KRW",
        "note": "매장 등록 메뉴 가격이며 총 식사비가 아닙니다. 안내용/0원/1원/누락 가격은 미확인으로 표시합니다.",
    }


def normalize_policy(
    payload: dict, person_count: int, table_type: str = "_ALL_"
) -> dict:
    data = payload.get("data")
    if not isinstance(data, dict) or type(data.get("hasEmptySlot")) is not bool:
        raise RuntimeError("예약 옵션 응답에 유효한 hasEmptySlot이 없습니다.")
    tables = data.get("tables")
    if tables is None:
        tables = (
            [data["defaultTable"]] if isinstance(data.get("defaultTable"), dict) else []
        )
    if not isinstance(tables, list):
        raise RuntimeError("예약 좌석 옵션 형식이 올바르지 않습니다.")
    options = []
    for table in tables:
        if not isinstance(table, dict):
            raise RuntimeError("예약 좌석 옵션 형식이 올바르지 않습니다.")
        if table_type != "_ALL_" and table.get("tableType") != table_type:
            continue
        menus = table.get("menuSets")
        deposits = []
        status, total = "unknown", None
        reservable = table.get("reservable")
        if reservable is False or data["hasEmptySlot"] is False:
            status = "unavailable"
        elif reservable is True and isinstance(menus, list):
            if not menus:
                status, total = "none", 0
            else:
                for menu in menus:
                    if not isinstance(menu, dict):
                        raise RuntimeError("예약 메뉴 옵션 형식이 올바르지 않습니다.")
                    per_person, cap = (
                        amount(menu.get("amountPerPerson")),
                        amount(menu.get("maxAmount")),
                    )
                    known = (
                        menu.get("menuType") == "DEPOSIT_PER_MAN"
                        and per_person is not None
                        and cap is not None
                    )
                    deposits.append(
                        {
                            "menu_set_seq": menu.get("menuSetSeq"),
                            "name": menu.get("name"),
                            "menu_type": menu.get("menuType"),
                            "amount_per_person": per_person,
                            "max_amount": cap,
                            "deposit_total": min(per_person * person_count, cap)
                            if known
                            else None,
                            "guide": menu.get("guideMessage"),
                        }
                    )
                values = {d["deposit_total"] for d in deposits}
                if len(values) == 1 and None not in values:
                    total = values.pop()
                    status = "required" if total > 0 else "none"
                elif any(d["menu_type"] == "MENU" for d in deposits) or len(values) > 1:
                    status = "selection_required"
            # Extra purchases may be mandatory. Do not infer a zero payable total.
            if table.get("addons"):
                status, total = "selection_required", None
        options.append(
            {
                "table_type": table.get("tableType"),
                "table_name": table.get("tableName"),
                "reservable": reservable if type(reservable) is bool else None,
                "deposit_status": status,
                "deposit_total": total,
                "menu_options": deposits,
                "addons": table.get("addons", []),
            }
        )
    eligible = [o for o in options if o["deposit_status"] != "unavailable"]
    statuses = {o["deposit_status"] for o in eligible}
    totals = {o["deposit_total"] for o in eligible}
    if not data["hasEmptySlot"]:
        status = "unavailable"
    elif not eligible:
        status = "unknown" if not tables else "unavailable"
    elif "unknown" in statuses:
        status = "unknown"
    elif len(statuses) > 1 or len(totals) > 1 or "selection_required" in statuses:
        status = "selection_required"
    else:
        status = statuses.pop()
    total = (
        totals.pop() if status in ("none", "required") and len(totals) == 1 else None
    )
    # The web app uses reservationPenaltyAvailable as isDepositFreeShop.
    # A configured deposit is not necessarily the amount paid at booking.
    zero_available = data.get("reservationPenaltyAvailable")
    zero_available = zero_available if type(zero_available) is bool else None
    if status == "unavailable":
        zero_available = None
    base_status, base_total = status, total
    if status == "required" and zero_available is not False:
        status = "conditional" if zero_available else "unknown"
        total = None
    for option in options:
        option["base_deposit_status"] = option["deposit_status"]
        option["base_deposit_total"] = option["deposit_total"]
        if option["deposit_status"] == "required" and zero_available is not False:
            option["deposit_status"] = "conditional" if zero_available else "unknown"
            option["deposit_total"] = None
    refunds = []
    policies = data.get("refundPolicies") or []
    if not isinstance(policies, list):
        raise RuntimeError("환불 규칙 응답 형식이 올바르지 않습니다.")
    for raw in policies:
        if not isinstance(raw, dict):
            raise RuntimeError("환불 규칙 응답 형식이 올바르지 않습니다.")
        day, rate = raw.get("baseDay"), raw.get("refundRate")
        valid_day = type(day) is int and day >= -1
        valid_rate = type(rate) in (int, float) and 0 <= rate <= 1
        refunds.append(
            {
                "days_before": day,
                "label": "노쇼"
                if day == -1
                else "당일"
                if day == 0
                else f"{day}일 전"
                if valid_day
                else "미확인",
                "refund_percent": round(rate * 100, 2) if valid_rate else None,
                "is_special_policy": raw.get("isSpecialPolicy"),
            }
        )
    return {
        "has_empty_slot": data["hasEmptySlot"],
        "table_selection_type": data.get("tableSelectionType"),
        "deposit_status": status,
        "deposit_required": True
        if status == "required"
        else False
        if status == "none"
        else None,
        "deposit_total": total,
        "base_deposit_status": base_status,
        "base_deposit_total": base_total,
        "zero_deposit_option": {
            "available": zero_available,
            "upfront_amount": 0 if zero_available is True else None,
            "requires_catchpay_card": True if zero_available is True else None,
            "user_eligibility_verified": False,
            "note": "캐치페이 카드 등록 후 예약금 0원 결제 선택 가능. 취소·노쇼 수수료는 매장 정책에 따라 등록 카드로 결제됩니다. 사용자별 적용 여부는 최종 예약서에서 확인하세요."
            if zero_available is True
            else "0원 결제 선택지 미제공 또는 미확인. 최종 예약서에서 확인하세요.",
        },
        "currency": "KRW",
        "table_options": options,
        "refund_policies": refunds,
        "reservation_penalty_available": data.get("reservationPenaltyAvailable"),
        "cancellation_charges": data.get("chargeAmounts", []),
        "scope": "base_deposit_total은 일반 예약금이며 실제 선결제액이 아닙니다. conditional은 캐치페이 카드 등록 후 0원 결제 선택지가 있다는 뜻입니다. 로그인·메뉴·추가상품·결제 방식에 따른 최종 청구액은 공식 예약서에서 확인하세요. 예약금 0원도 취소 수수료 면제를 뜻하지 않습니다.",
        "reservation_created": False,
    }
