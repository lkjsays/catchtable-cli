# 에이전트 식당 조회·예약 준비 — 2026-10-12

## 2026-10-13 최종 상태

메뉴·가격과 예약 정책 CLI까지 추가했으며 프로젝트 및 전역 실행 환경에서 각각 58 tests를 통과했다. 예약금 일반 결제와 캐치페이 0원 결제 선택지를 분리한 상세 계약은 [메뉴·정책 검증](menu-policy-2026-10-13.md)에 기록했다.

공식 Chrome 웹앱은 초기 footer만 보인 뒤 정상 로딩됐고 사용자가 브라우저 로그인을 완료했다. 보안 설정 변경은 없었고 초기 빈 화면의 근본 원인은 확정하지 못했다. 메즈클라 예약서까지 확인했지만 사용자가 실제 예약 진행을 중단해 최종 예약·결제는 실행하지 않았다. 직접 예약 생성 API는 여전히 미구현이며 CLI 인증 내 예약 조회도 실제 계정으로 검증하지 않았다.

이하 2026-10-12 검증 당시 기록의 빈 화면·로그인 대기 설명은 과거 상태다.

## 현재 사용 가능한 기능

- 일반 `uv run ct ...`에서 공개 조회 성공. 임시 SSL 주입 없이 시스템 신뢰 저장소 사용.
- 식당명 검색 `search keyword`, 지역/음식 검색, 자동완성.
- `recommend`: 후보의 실제 평점·리뷰·가격·가능 시간을 포함한 설명 가능한 추천.
- `shop availability`: 공개 키 발급과 RSA PKCS#1 v1.5 암호화를 포함한 실제 예약 시간 조회.
- `reserve`: 최신 시간 재조회, 선택 시간 검증, 날짜·인원이 포함된 공식 매장 URL 제공. **예약 생성 없음.**
- `auth login/status/logout`: 숨김 입력, 세션 검증 후 OS 저장소 저장/삭제. 비밀값 출력 없음.
- `reservations list`: 인증된 사용자의 예정 예약 조회 및 커서 전달.
- `doctor`: TLS·공개 API·인증 설정 상태 진단.
- `/Users/kjlee/.codex/skills/catchtable-cli` → 소스 디렉터리 심볼릭 링크로 에이전트 스킬 연결. 유효성 검사 통과.

## 실제 검증 결과

수정 전에는 새 Python 환경의 인증서 저장소로 서비스 인증서를 확인하지 못했다. 수정 후 `truststore.SSLContext`를 httpx에 직접 전달한다. 프로세스 전역 패치, verify=False, OS 신뢰 설정 변경은 하지 않았다. 명시적인 CA 환경 변수가 있으면 그 설정을 사용한다.

일반 실행으로 확인한 명령:

```bash
uv run ct doctor
uv run ct search search 스시 --limit 2 --fields label,item_type
uv run ct search keyword 우래옥 --page-size 3 --fields shop_name,shop_url,land_name
uv run ct recommend --region 강남 --date 2026-10-18 --person-count 1 --available-only --limit 2 --candidates 5
uv run ct shop availability sushi_hakusha --date 2026-10-18 --person-count 1 --format compact
uv run ct reserve sushi_hakusha --date 2026-10-18 --time 12:00 --person-count 1
```

- doctor: `public_api=reachable`, `tls_verification=enabled`, `trust_store=OS native`, `active_transport=httpx`.
- 식당명 검색: 우래옥(을지로), 우래옥 모밀 2건과 alias 반환.
- 추천: 스시하쿠샤, 시드니 서울 등 실제 조회 후보의 별점·리뷰·가능 시간·가격 문구 반환.
- 시간 조회: 스시하쿠샤 2026-10-18 1명, 12:00와 18:00 관측.
- 예약 준비: 같은 매장의 12:00을 재조회해 `ready_for_browser`, `reservation_created=false`와 공식 URL 반환.
- 로그인: 저장된 CLI 쿠키 없음. 무인증 `/api/v3/user/myMain`은 실제 HTTP 401. 인증된 조회와 저장은 아직 실제 계정으로 검증하지 않음.

모든 좌석·가격·추천은 조회 시점의 정보다. 슬롯이 실제로 조회 사이에 바뀔 수 있으므로 예약 준비에서 재조회한다. 공개 키·challenge·응답 서명은 결과에 출력하거나 파일에 보존하지 않는다.

## 예약 확정의 남은 조건

**완전 자동 예약 확정까지 구현·실증한 상태는 아니다.** 기존의 단순 `shopRef/date/time/personCount` POST는 실제 웹앱의 예약 계약을 충족하지 않는다. 웹앱은 시간 검증, 좌석 holding, 메뉴/추가 옵션, form, 예약금/취소 조건, 약관, 최종 create를 연결한다. 검증하지 않은 본문으로 create를 호출하는 기존 client.reserve 경로는 명시적인 미지원 오류로 교체했다.

이번 작업에서는 사용자가 특정 예약 대상·일시·인원·금액을 지정하지 않았고 로그인 세션도 없었다. 실제 좌석 확보·예약·결제·약관 동의는 실행하지 않았다. 예약 생성 API 직접 호출은 미구현이며, 에이전트 스킬은 구체적인 예약 요청을 받으면 공식 화면에서 진행하고 완료 화면/예약 내역을 확인하도록 안내한다.

공식 매장 URL을 Codex 브라우저와 연결된 Chrome에서 열었으나 두 환경 모두 웹앱 본문이 빈 화면으로 남았다. URL 및 웹앱 코드의 date/time/personCount 파라미터는 확인했으나 화면 반영·로그인·확정까지는 검증하지 못했다. 추후 공식 웹앱 로딩과 로그인이 가능한 환경에서 해당 흐름을 확인해야 한다. 사이트 표시 문제를 성공으로 처리하거나 보안 설정을 바꾸지 않았다.

사용자에게 남은 최소 조치는 구체적인 식당·일시·인원 선택과 공식 로그인이다. CLI에서 내 예약도 조회하려면 `ct auth login`의 로컬 숨김 프롬프트로 본인 x-ct-a를 저장하면 된다. 브라우저로만 예약을 진행할 때는 쿠키를 CLI로 가져올 필요가 없다.

## 자동 검증과 패키징

`uv run python -m unittest discover -s tests -v`로 기본 회귀, RSA 복호화 대조, 다음 날 슬롯, 날짜·인원 불일치, 예약 미생성/슬롯 없음, 추천 기준, 인증 저장 전 확인과 비밀값 미출력, 예약 내역 커서, TLS 검증 유지, 쓰기 실패 무재전송을 검사한다.

로컬 HTTPS 서버의 신뢰되지 않는 인증서 연결은 실제 거부되고, 해당 테스트 CA를 명시했을 때만 연결이 성공한다. 임시 테스트 인증서를 OS에 설치하지 않는다. 인증 저장은 대체 저장소로 테스트하므로 실제 키체인을 변경하지 않는다.

개발 uv 환경과 전역 설치 환경에서 각각 **44개 테스트 통과**. `uv build`로 sdist와 wheel 생성 성공. 저장소 밖의 깨끗한 wheel 설치 환경에서도 doctor의 실제 연결이 성공했다.

기존 `/Users/kjlee/.local/bin/ct`가 이 저장소 editable 설치임을 확인하고 해당 uv tool 환경을 새 의존성으로 갱신했다. 이제 `uv run` 없이 일반 `ct doctor`, `ct search keyword ...`도 동작한다. 최신 Typer 0.27의 Click 전이 의존성 제거로 발견한 schema 오류도 수정하고 전역 설치 환경에서 검증했다.

검사 명령은 `uvx ruff check --isolated --select F,I catchtable_cli tests`, 형식 검사와 `git diff --check`도 통과했다. 최종 상태와 정확한 재개 위치는 `.autopilot/agent-dining/03_progress.md`에 기록했다.
