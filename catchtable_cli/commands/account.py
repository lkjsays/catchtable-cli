"""Local authentication setup and read-only account verification."""

from __future__ import annotations

import sys

import typer

from catchtable_cli.client import CatchTableClient
from catchtable_cli.commands.common import fail, print_json, run
from catchtable_cli.config import CatchTableConfig
from catchtable_cli.credentials import remove_cookie, save_cookie
from catchtable_cli.requests import Request

auth_app = typer.Typer(help="로그인 세션 설정·상태 (비밀값 출력 없음)")
reservations_app = typer.Typer(help="기존 예약 확인")


@auth_app.command("status")
def auth_status(
    check: bool = typer.Option(False, "--check", help="서버에서 세션 유효성 확인"),
) -> None:
    """쿠키 저장 여부를 확인합니다. --check 없이는 로그인 성공을 단정하지 않습니다."""

    async def execute():
        client = CatchTableClient()
        try:
            configured = bool(client.config.session_cookie)
            if check:
                if not configured:
                    fail(
                        "로그인 세션이 없습니다. ct auth login 또는 CT_SESSION_COOKIE를 설정하세요.",
                        3,
                    )
                result = await client._request("GET", "/api/v3/user/myMain")
                if not isinstance(result.get("data"), dict) or not result["data"]:
                    raise RuntimeError("로그인 상태를 확인할 수 없는 응답입니다.")
            return {
                "ok": True,
                "credential_configured": configured,
                "authenticated": True if check else None,
                "login_url": "https://app.catchtable.co.kr/ct/login",
                "hint": "ct auth login으로 x-ct-a 세션을 OS 자격 증명 저장소에 저장할 수 있습니다.",
            }
        finally:
            await client.close()

    print_json(run(execute()))


@auth_app.command("login")
def auth_login(
    cookie_stdin: bool = typer.Option(
        False, "--cookie-stdin", help="쿠키를 명령행 인자 대신 표준 입력으로 받음"
    ),
) -> None:
    """사용자가 전달한 x-ct-a를 검증한 뒤 OS 자격 증명 저장소에 저장합니다."""
    from catchtable_cli.validate import require_text

    try:
        cookie = (
            sys.stdin.read().strip()
            if cookie_stdin
            else typer.prompt("x-ct-a 세션 쿠키", hide_input=True)
        )
        cookie = require_text(cookie, "세션 쿠키")
        if any(c in cookie for c in ";\r\n"):
            raise ValueError("Cookie 헤더 전체가 아니라 x-ct-a 값만 입력하세요.")
    except ValueError as exc:
        fail(str(exc))

    async def execute():
        # Importing credentials only contacts the canonical service, never an API override.
        client = CatchTableClient(
            CatchTableConfig(
                api_base_url="https://ct-api.catchtable.co.kr",
                session_cookie=cookie,
                use_keychain=False,
            )
        )
        try:
            result = await client._request("GET", "/api/v3/user/myMain")
            if not isinstance(result.get("data"), dict) or not result["data"]:
                raise RuntimeError("로그인 상태를 확인할 수 없는 응답입니다.")
            save_cookie(cookie)
            return {
                "ok": True,
                "authenticated": True,
                "stored_in": "OS credential store",
            }
        finally:
            await client.close()

    print_json(run(execute()))


@auth_app.command("logout")
def auth_logout() -> None:
    """이 CLI에 저장한 세션만 삭제합니다. 환경 변수와 브라우저 로그인은 유지됩니다."""
    try:
        remove_cookie()
    except RuntimeError as exc:
        fail(str(exc), 1)
    print_json(
        {
            "ok": True,
            "stored_credential_removed": True,
            "note": "CT_SESSION_COOKIE가 설정돼 있다면 직접 해제하세요.",
        }
    )


@reservations_app.command("list")
def reservations_list(
    size: int = typer.Option(10, "--size", min=1, max=100),
    cursor: str | None = typer.Option(None, "--cursor", help="직전 data.scrollKey"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """로그인한 계정의 예정된 예약을 조회합니다. 예약 생성·변경·취소는 하지 않습니다."""
    params = {"statusGroup": "PLANNED", "sortCode": "DESC", "size": size}
    if cursor:
        from catchtable_cli.validate import require_text

        try:
            params["scrollKey"] = require_text(cursor, "cursor")
        except ValueError as exc:
            fail(str(exc))
    request = Request("GET", "/api/v4/user/reservations/_list", params=params)
    if dry_run:
        print_json({"command": "reservations list", **request.plan()})
        return

    async def execute():
        client = CatchTableClient()
        try:
            if not client.config.session_cookie:
                fail("로그인이 필요합니다. ct auth login 후 다시 실행하세요.", 3)
            result = await request.send(client)
            if not isinstance(result.get("data"), dict):
                raise RuntimeError("예약 목록 응답 형식이 올바르지 않습니다.")
            return {"ok": True, "data": result["data"], "scope": "PLANNED"}
        finally:
            await client.close()

    print_json(run(execute()))


def doctor(
    offline: bool = typer.Option(False, "--offline", help="네트워크 연결 확인 생략"),
) -> None:
    """비밀값을 출력하지 않고 TLS·공개 API·인증 설정을 진단합니다."""
    import os

    from catchtable_cli.requests import autocomplete_request

    async def execute():
        client = CatchTableClient()
        try:
            if not offline:
                await autocomplete_request({"query": "스시"}).send(client)
            return {
                "ok": True,
                "tls_verification": "enabled",
                "trust_store": "explicit CA environment"
                if os.getenv("SSL_CERT_FILE") or os.getenv("SSL_CERT_DIR")
                else "OS native",
                "public_api": "not_checked" if offline else "reachable",
                "active_transport": "curl_cffi" if client._use_curl_cffi else "httpx",
                "credential_configured": bool(client.config.session_cookie),
                "booking_mode": "official_browser_handoff",
                "agent_skill": "catchtable-cli",
            }
        finally:
            await client.close()

    print_json(run(execute()))
