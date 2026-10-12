from __future__ import annotations

import asyncio
import json
from enum import Enum
from typing import Any

import httpx
import typer
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from catchtable_cli.client import CatchTableAPIError

err_console = Console(stderr=True)


class OutputFormat(str, Enum):
    json = "json"
    table = "table"
    compact = "compact"


def fail(message: str, code: int = 2) -> None:
    err_console.print(message, markup=False)
    raise typer.Exit(code)


def error_info(exc: Exception) -> tuple[int, str]:
    if isinstance(exc, CatchTableAPIError):
        return (
            3
            if str(exc.result_code).upper()
            in {
                "401",
                "403",
                "UNAUTHORIZED",
                "FORBIDDEN",
                "AUTH",
                "LOGIN_REQUIRED",
                "NEED_LOGIN",
            }
            else 1,
            str(exc),
        )
    if isinstance(exc, httpx.HTTPStatusError):
        return (
            3 if exc.response.status_code in (401, 403) else 1,
            f"HTTP {exc.response.status_code}: {exc.response.reason_phrase}",
        )
    if isinstance(exc, (ValidationError, ValueError)):
        return 1, "API 응답 형식이 올바르지 않습니다."
    return 1, str(exc)


def run(coro):
    try:
        return asyncio.run(coro)
    except typer.Exit:
        raise
    except (CatchTableAPIError, httpx.HTTPError, RuntimeError, ValueError) as exc:
        code, message = error_info(exc)
        fail(message, code)


def field_names(fields: str | None, model: type) -> list[str]:
    names = [s.strip() for s in fields.split(",")] if fields is not None else []
    valid = set(model.model_fields) | set(model.model_computed_fields)
    if any(n not in valid for n in names):
        raise ValueError(f"잘못된 --fields. 허용 필드: {', '.join(sorted(valid))}")
    return names


def select(data: dict, fields: list[str]) -> dict:
    return {name: data.get(name) for name in fields} if fields else data


def print_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def cell(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "Y" if value else "N"
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return str(value).replace("\t", " ").replace("\n", " ")


def rows_output(
    rows: list[dict], fields: list[str], fmt: OutputFormat, title: str
) -> None:
    if fmt == OutputFormat.compact:
        for row in rows:
            print("\t".join(cell(row.get(f)) for f in fields))
    else:
        table = Table(title=title)
        for name in fields:
            table.add_column(name)
        for row in rows:
            table.add_row(*(cell(row.get(f)) for f in fields))
        err_console.print(table)
