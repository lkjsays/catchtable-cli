"""Schemas derived from the actual Click/Typer command definitions."""

from __future__ import annotations

from typing import Any

from typer.main import get_command

from catchtable_cli.models import (
    AutocompleteSuggestion,
    DaySlot,
    SearchShop,
    ShopDetail,
)
from catchtable_cli.requests import SORT_TYPES

EXIT_CODES = {
    "0": "성공",
    "1": "API/네트워크/응답 형식 오류",
    "2": "입력 오류",
    "3": "인증/권한 오류",
    "4": "부분 실패 (매장 상세 성공, 예약 날짜 조회 실패)",
    "5": "요청한 예약 시간 확인 불가",
}
EXTRA_OUTPUTS = {
    "shop menu": {
        "ok": "boolean",
        "alias": "string",
        "observed_at": "string",
        "source": "string",
        "items": "array",
        "notices": "array",
        "menu_boards": "array",
        "last_updated_at": ["string", "null"],
        "alcohol_order_required": ["boolean", "null"],
        "corkage_guide": ["string", "null"],
        "price_status": "string",
        "currency": "string",
        "note": "string",
    },
    "shop policy": {
        "ok": "boolean",
        "alias": "string",
        "shop_ref": "string",
        "shop_name": ["string", "null"],
        "date": "string",
        "time": "string",
        "person_count": "integer",
        "observed_at": "string",
        "source": "object",
        "has_empty_slot": "boolean",
        "table_selection_type": ["string", "null"],
        "deposit_status": "string",
        "deposit_required": ["boolean", "null"],
        "deposit_total": ["integer", "null"],
        "base_deposit_status": "string",
        "base_deposit_total": ["integer", "null"],
        "zero_deposit_option": "object",
        "currency": "string",
        "table_options": "array",
        "refund_policies": "array",
        "reservation_penalty_available": ["boolean", "null"],
        "cancellation_charges": "array",
        "scope": "string",
        "reservation_created": "boolean",
    },
    "shop availability": {
        "ok": "boolean",
        "shop_ref": "string",
        "alias": "string",
        "shop_name": "string",
        "service_date": "string",
        "person_count": "integer",
        "observed_at": "string",
        "availability_status": "string",
        "slots": "array",
        "metadata": "object",
        "booking_url": "string",
    },
    "recommend": {
        "ok": "boolean",
        "observed_at": "string",
        "region_code": "string",
        "date": ["string", "null"],
        "person_count": ["integer", "null"],
        "candidate_count": "integer",
        "total_matches": ["integer", "null"],
        "items": "array",
        "ranking": "object",
        "scope": "string",
        "next_step": "string",
    },
    "reserve": {
        "ok": "boolean",
        "status": "string",
        "reservation_created": "boolean",
        "shop_name": "string",
        "shop_ref": "string",
        "service_date": "string",
        "service_time": "string",
        "person_count": "integer",
        "observed_at": "string",
        "slots": "array",
        "booking_url": ["string", "null"],
        "next_action": "string",
        "completion_evidence": "string",
    },
    "reservations list": {"ok": "boolean", "data": "object", "scope": "string"},
    "auth status": {
        "ok": "boolean",
        "credential_configured": "boolean",
        "authenticated": ["boolean", "null"],
        "login_url": "string",
        "hint": "string",
    },
    "auth login": {"ok": "boolean", "authenticated": "boolean", "stored_in": "string"},
    "auth logout": {
        "ok": "boolean",
        "stored_credential_removed": "boolean",
        "note": "string",
    },
    "doctor": {
        "ok": "boolean",
        "tls_verification": "string",
        "trust_store": "string",
        "public_api": "string",
        "active_transport": "string",
        "credential_configured": "boolean",
        "booking_mode": "string",
        "agent_skill": "string",
    },
}
MODELS = {
    "search search": AutocompleteSuggestion,
    "search region": SearchShop,
    "search keyword": SearchShop,
    "shop info": ShopDetail,
}


def list_commands() -> list[str]:
    return sorted(set(MODELS) | set(EXTRA_OUTPUTS))


def get_command_schema(command: str) -> dict[str, Any] | None:
    if command not in list_commands():
        return None
    from catchtable_cli.cli import app

    cmd = get_command(app)
    for part in command.split():
        cmd = cmd.commands[part]
    parameters = {}
    for param in cmd.params:
        key = param.opts[0]
        # New Typer vendors its parameter types; avoid a transitive Click import.
        type_name = param.type.name.lower()
        kind = (
            "boolean"
            if type_name in {"bool", "boolean"}
            else "integer"
            if type_name.startswith("int")
            else "number"
            if type_name.startswith("float")
            else "string"
        )
        spec = {
            "type": kind,
            "required": param.required,
            "default": param.default,
            "description": getattr(param, "help", None),
        }
        if hasattr(param.type, "choices"):
            spec["enum"] = list(param.type.choices)
        if hasattr(param.type, "min") and hasattr(param.type, "max"):
            spec.update({"min": param.type.min, "max": param.type.max})
        if key == "--sort":
            spec["enum"] = list(SORT_TYPES)
        parameters[key] = spec
    if command in EXTRA_OUTPUTS:
        props = {key: {"type": kind} for key, kind in EXTRA_OUTPUTS[command].items()}
        for value in props.values():
            if value["type"] == "array":
                value["items"] = {"type": "object"}
        if command == "shop policy":
            props["deposit_status"] = {
                "enum": [
                    "none",
                    "required",
                    "conditional",
                    "selection_required",
                    "unknown",
                    "unavailable",
                ]
            }
        if command == "shop menu":
            props["price_status"] = {"enum": ["listed", "unknown"]}
        if command == "recommend":
            props["items"]["items"] = SearchShop.model_json_schema(by_alias=False)
            props["items"]["items"]["properties"].update(
                {
                    "score": {"type": "number"},
                    "available_times": {"type": "array", "items": {"type": "string"}},
                    "availability_verified": {"type": "boolean"},
                    "reasons": {"type": "array", "items": {"type": "string"}},
                    "booking_url": {"type": "string"},
                }
            )
        if "slots" in props:
            props["slots"]["items"] = {
                "type": "object",
                "properties": {
                    "date": {"type": "string"},
                    "time": {"type": "string"},
                    "service_time": {"type": "string"},
                    "available": {"type": ["boolean", "null"]},
                    "person_count": {"type": "integer"},
                    "table_type": {"type": ["string", "null"]},
                    "confirmation_required": {"type": ["boolean", "null"]},
                    "menu_set_seq": {"type": ["integer", "null"]},
                },
            }
        return {
            "description": cmd.help,
            "parameters": parameters,
            "response_model": {"type": "object", "properties": props},
            "exit_codes": EXIT_CODES,
        }
    model = MODELS[command]
    row_schema = model.model_json_schema(by_alias=False)
    properties: dict[str, Any] = {"ok": {"type": "boolean"}}
    if command == "shop info":
        properties.update(
            {
                "partial": {"type": "boolean"},
                "alias": {"type": "string"},
                "shop_ref": {"type": "string"},
                "shop": row_schema,
                "day_slots_status": {"enum": ["ok", "empty", "error"]},
                "day_slots": {
                    "type": "array",
                    "items": DaySlot.model_json_schema(by_alias=False),
                },
                "errors": {"type": "array", "items": {"type": "object"}},
            }
        )
    else:
        properties.update(
            {
                "items": {"type": "array", "items": row_schema},
                "total": {"type": ["integer", "null"]},
                "returned": {"type": "integer"},
            }
        )
        if command in {"search region", "search keyword"}:
            properties.update(
                {
                    "region_code": {"type": ["string", "null"]},
                    "next_cursor": {"type": ["string", "null"]},
                }
            )
        else:
            properties["suggestions"] = {"type": "array", "items": {"type": "string"}}
    return {
        "description": cmd.help,
        "parameters": parameters,
        "response_model": {"type": "object", "properties": properties},
        "field_model": row_schema,
        "exit_codes": EXIT_CODES,
    }
