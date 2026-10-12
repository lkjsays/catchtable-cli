"""캐치테이블 CLI 진입점.

Agent DX 원칙 적용:
- 3. Runtime Schema Introspection: schema 서브커맨드
- 1. JSON-First Output: 종료 코드 체계화
"""

from __future__ import annotations

import json

import typer
from rich.console import Console

from catchtable_cli import __version__
from catchtable_cli.commands.account import auth_app, doctor, reservations_app
from catchtable_cli.commands.recommend import recommend
from catchtable_cli.commands.reserve import reserve
from catchtable_cli.commands.search import search_app
from catchtable_cli.commands.shop import shop_app

# stderr 전용 콘솔
err_console = Console(stderr=True)

app = typer.Typer(
    name="ct",
    help="캐치테이블 비공식 CLI",
    no_args_is_help=True,
)

app.add_typer(search_app, name="search")
app.add_typer(shop_app, name="shop")
app.add_typer(auth_app, name="auth")
app.add_typer(reservations_app, name="reservations")
app.command("recommend")(recommend)
app.command("reserve")(reserve)
app.command("doctor")(doctor)

# schema 서브앱 (원칙 3: Runtime Schema Introspection)
schema_app = typer.Typer(help="커맨드 스키마 자체검사")
app.add_typer(schema_app, name="schema")


@schema_app.command("show")
def schema_show(
    command: str = typer.Argument(
        ...,
        help="스키마를 조회할 커맨드 (예: 'search region', 'shop info')",
    ),
) -> None:
    """커맨드의 파라미터/응답/exit code 스키마를 JSON으로 출력합니다."""
    from catchtable_cli.schema import get_command_schema

    schema = get_command_schema(command)
    if schema is None:
        err_console.print(f"[red]알 수 없는 커맨드: {command!r}[/red]")
        err_console.print(
            "[yellow]사용 가능한 커맨드 목록은 'ct schema list'를 실행하세요.[/yellow]"
        )
        raise typer.Exit(code=2)

    print(json.dumps(schema, ensure_ascii=False, indent=2))


@schema_app.command("list")
def schema_list() -> None:
    """스키마가 등록된 커맨드 목록을 출력합니다."""
    from catchtable_cli.schema import list_commands

    commands = list_commands()
    output = {"commands": commands}
    print(json.dumps(output, ensure_ascii=False, indent=2))


@app.command()
def notify() -> None:
    """빈자리 알림을 설정합니다. (미구현)"""
    err_console.print("[red]notify 커맨드는 아직 구현되지 않았습니다.[/red]")
    raise typer.Exit(1)


@app.command()
def version() -> None:
    """버전을 출력합니다."""
    typer.echo(f"catchtable-cli v{__version__}")


@app.command()
def overview() -> None:
    """CLI 개요를 출력합니다."""
    typer.echo(
        f"catchtable-cli v{__version__}\n"
        "캐치테이블 비공식 CLI\n\n"
        "사용 가능한 명령어:\n"
        "  search   매장 검색\n"
        "  shop     매장 정보 조회\n"
        "  schema   커맨드 스키마 조회\n"
        "  recommend  조건에 맞는 식당 추천\n"
        "  reserve  최신 시간 확인 후 공식 예약 화면 연결\n"
        "  reservations  내 예약 확인\n"
        "  auth     세션 설정/확인\n"
        "  doctor   연결 진단\n"
        "  notify   빈자리 알림 (미구현)\n"
        "  version  버전 출력"
    )
