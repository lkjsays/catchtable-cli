"""Optional native credential storage; never fall back to a plaintext file."""

from __future__ import annotations

import sys

SERVICE = "catchtable-cli"
ACCOUNT = "x-ct-a"


def backend():
    if sys.platform == "darwin":
        from keyring.backends.macOS import Keyring
    elif sys.platform == "win32":
        from keyring.backends.Windows import WinVaultKeyring as Keyring
    else:
        from keyring.backends.SecretService import Keyring
    return Keyring()


def read_cookie() -> str:
    try:
        return backend().get_password(SERVICE, ACCOUNT) or ""
    except Exception:
        # Public searches should still work when the credential store is locked.
        return ""


def save_cookie(value: str) -> None:
    try:
        backend().set_password(SERVICE, ACCOUNT, value)
    except Exception as exc:
        raise RuntimeError(
            "OS 자격 증명 저장소에 저장하지 못했습니다. CT_SESSION_COOKIE 환경 변수를 사용할 수 있습니다."
        ) from exc


def remove_cookie() -> None:
    from keyring.errors import PasswordDeleteError

    try:
        backend().delete_password(SERVICE, ACCOUNT)
    except PasswordDeleteError:
        pass
    except Exception as exc:
        raise RuntimeError("OS 자격 증명 저장소를 확인하지 못했습니다.") from exc
