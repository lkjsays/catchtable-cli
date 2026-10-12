"""입력 검증 유틸리티 모듈 (Agent DX 원칙 4: Input Hardening)."""

from __future__ import annotations

import unicodedata

# 거부할 위험 유니코드 코드포인트 집합
_DANGEROUS_UNICODE = frozenset(
    [
        "\u200b",  # Zero Width Space
        "\u200c",  # Zero Width Non-Joiner
        "\u200d",  # Zero Width Joiner
        "\u200e",  # Left-to-Right Mark
        "\u200f",  # Right-to-Left Mark
        "\u202a",  # Left-to-Right Embedding
        "\u202b",  # Right-to-Left Embedding
        "\u202c",  # Pop Directional Formatting
        "\u202d",  # Left-to-Right Override
        "\u202e",  # Right-to-Left Override (특히 위험)
        "\u2060",  # Word Joiner
        "\u2061",  # Function Application
        "\u2062",  # Invisible Times
        "\u2063",  # Invisible Separator
        "\u2064",  # Invisible Plus
        "\ufeff",  # BOM / Zero Width No-Break Space
    ]
)

# 경로순회에 사용되는 문자 집합
_PATH_TRAVERSAL_CHARS = frozenset([".", "/", "\\", ":", "*", "?", '"', "<", ">", "|"])


def sanitize_text(value: str, *, field_name: str = "입력값") -> str:
    """텍스트 입력을 검증하고 NFC 정규화하여 반환.

    다음 항목을 거부합니다:
    - ASCII 제어문자 (0x00-0x1F, 0x7F)
    - 위험 유니코드 문자
    - 이중 인코딩 패턴 (% 포함)

    Returns:
        NFC 정규화된 문자열

    Raises:
        ValueError: 유효하지 않은 입력
    """
    # 제어문자 거부 (ASCII 0x00-0x1F, 0x7F)
    for ch in value:
        code = ord(ch)
        if (0x00 <= code <= 0x1F) or code == 0x7F:
            raise ValueError(
                f"{field_name}에 제어문자(U+{code:04X})가 포함되어 있습니다."
            )

    # 위험 유니코드 거부
    for ch in value:
        if ch in _DANGEROUS_UNICODE:
            raise ValueError(
                f"{field_name}에 위험한 유니코드 문자(U+{ord(ch):04X})가 포함되어 있습니다."
            )

    # 이중 인코딩 방지 (% 포함 거부)
    if "%" in value:
        raise ValueError(
            f"{field_name}에 퍼센트 인코딩 문자(%)가 포함되어 있습니다. 디코딩된 값을 사용하세요."
        )

    # NFC 정규화
    return unicodedata.normalize("NFC", value)


def sanitize_identifier(value: str, *, field_name: str = "식별자") -> str:
    """alias, shop_id 등 식별자 검증.

    sanitize_text 검증에 더해 경로순회 문자를 거부합니다.

    Returns:
        NFC 정규화된 식별자 문자열

    Raises:
        ValueError: 유효하지 않은 입력
    """
    # 기본 텍스트 검증
    value = sanitize_text(value, field_name=field_name)

    # 경로순회 문자 거부
    for ch in value:
        if ch in _PATH_TRAVERSAL_CHARS:
            raise ValueError(
                f"{field_name}에 경로순회 문자('{ch}')가 포함되어 있습니다."
            )

    return value


def require_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field}는 비어 있지 않은 문자열이어야 합니다.")
    return sanitize_text(value.strip(), field_name=field)


def validate_date(value: object) -> str:
    import re
    from datetime import date

    if not isinstance(value, str) or not re.fullmatch(
        r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value
    ):
        raise ValueError("날짜는 YYYY-MM-DD 형식이어야 합니다.")
    try:
        date.fromisoformat(value)
    except ValueError:
        raise ValueError("실제로 존재하는 날짜를 입력하세요.") from None
    return value


def positive_int(value: object, field: str) -> int:
    if type(value) is not int or value < 1:
        raise ValueError(f"{field}는 양의 정수여야 합니다.")
    return value


def parse_body(value: str) -> dict:
    import json

    def reject_constant(value):
        raise ValueError(f"잘못된 JSON 상수: {value}")

    try:
        body = json.loads(value, parse_constant=reject_constant)
    except ValueError:
        raise ValueError("--json-body: 올바른 JSON을 입력하세요.") from None
    if not isinstance(body, dict):
        raise ValueError("--json-body는 JSON 객체여야 합니다.")
    return body


def parse_params(value: str | None) -> dict[str, str]:
    result = {}
    if value is None:
        return result
    for pair in value.split(","):
        key, sep, val = pair.partition("=")
        if not sep or not key.strip():
            raise ValueError("--params는 key=value 형식이어야 합니다.")
        result[require_text(key, "파라미터 이름")] = sanitize_text(val.strip())
    return result


def validate_search_body(body: dict) -> None:
    # Unknown keys remain available for deliberate API passthrough. Reject the old
    # silently ignored CLI contract rather than pretending those filters work.
    legacy = set(body) & {
        "region",
        "category",
        "visitDate",
        "personCount",
        "foodKindCode",
        "sortMethod",
    }
    if legacy:
        raise ValueError(
            f"지원하지 않는 최상위 검색 필드: {', '.join(sorted(legacy))}. filters/reservationParams/sort를 사용하세요."
        )
    for name in ("filters", "paging", "sort", "reservationParams", "keywordSearch"):
        if name in body and not isinstance(body[name], dict):
            raise ValueError(f"{name}는 객체여야 합니다.")
    reservation = body.get("reservationParams", {})
    if "reservationDate" in reservation:
        validate_date(reservation["reservationDate"])
    if "personCount" in reservation:
        positive_int(reservation["personCount"], "personCount")
    paging = body.get("paging", {})
    if "page" in paging:
        raise ValueError(
            "paging.page는 미지원입니다. 서버의 next_cursor를 paging.offset에 사용하세요."
        )
    if "size" in paging and positive_int(paging["size"], "paging.size") > 100:
        raise ValueError("paging.size는 100 이하여야 합니다.")
    if "offset" in paging:
        require_text(paging["offset"], "paging.offset")
    for name in ("displayRegionCodes", "legalDistrictCodes", "foodKindCodes"):
        values = body.get("filters", {}).get(name)
        if values is not None:
            if not isinstance(values, list):
                raise ValueError(f"filters.{name}는 문자열 배열이어야 합니다.")
            for value in values:
                require_text(value, name)
    if "sortType" in body.get("sort", {}):
        require_text(body["sort"]["sortType"], "sort.sortType")
    if "keyword" in body.get("keywordSearch", {}):
        require_text(body["keywordSearch"]["keyword"], "keywordSearch.keyword")


def validate_time(value: str) -> str:
    import re

    # The booking service represents after-midnight slots as 24:00..29:59.
    if not re.fullmatch(r"(?:[01][0-9]|2[0-9]):[0-5][0-9]", value):
        raise ValueError(
            "시간은 HH:MM 형식 (00:00~29:59)이어야 합니다. 자정 이후 슬롯은 service_time을 사용하세요."
        )
    return value
