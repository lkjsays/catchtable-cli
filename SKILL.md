---
name: catchtable-cli
description: 캐치테이블의 실제 응답으로 식당을 검색·추천하고 인원별 예약 시간을 확인한다. 사용자가 맛집 후보를 찾거나 캐치테이블 검색·예약 진행·내 예약 확인을 요청할 때 사용한다. 예약은 최신 시간 확인 후 공식 화면으로 이어가며 완료 근거를 확인한다.
---

# CatchTable dining assistant

## 실행

이 Mac의 소스는 `/Users/kjlee/Projects/catchtable-cli`다. 다른 작업 폴더에서도 다음 형태로 실행한다.

```bash
uv run --directory /Users/kjlee/Projects/catchtable-cli ct doctor
uv run --directory /Users/kjlee/Projects/catchtable-cli ct schema list
```

처음 사용하거나 연결 실패가 있을 때 doctor로 TLS·공개 API를 확인한다. 평소 매 요청마다 진단할 필요는 없다. 인증서 검증은 유지한다. `truststore`를 별도로 주입할 필요가 없다.

## 식당 찾기와 추천

식당명 검색은 `search keyword`, 음식·지역 코드 탐색은 `search search`, 지역 매장 목록은 `search region`을 사용한다. 식당 alias는 검색 결과 `shop_url`에 있다.

```bash
ct search keyword '우래옥' --page-size 5
ct search search '스시' --fields label,item_type,code --limit 5
ct search region --region '부산' --sort REVIEW --page-size 10
ct recommend --region '강남' --food-kind E_31 --limit 5
ct recommend --region '강남' --date 2026-10-18 --person-count 2 --available-only --limit 3
```

위 예제의 `ct`도 실제 실행에서는 `uv run --directory /Users/kjlee/Projects/catchtable-cli ct`로 호출한다. 날짜는 예시를 재사용하지 말고 사용자의 지역 시간과 요청에서 정한다.

지역·음식·날짜·인원·예산·분위기 중 이미 주어진 조건은 다시 묻지 않는다. 추천에 필요한 누락 조건만 확인한다. 날짜가 없으면 평점·리뷰 기반 후보를 먼저 제시할 수 있다. 평점, 리뷰 수, 지역, API가 제공한 가격, 조회 시점과 선택 이유를 사용한다. 메뉴 가격을 총 식사비나 예약금으로 단정하지 않는다. 알레르기·접근성·좌석 유형처럼 응답에 없는 정보는 매장 확인 대상으로 남긴다.

추천 순위는 검색 첫 페이지 안에서 `(평점×리뷰수+4.0×20)/(리뷰수+20)`으로 계산한 참고 순위다. 사용자 취향이 이 점수보다 우선한다. 전체 지역 최적 식당으로 과장하지 않는다. 결과가 없으면 조건 완화를 제안하거나 다른 커서를 조회한다. 예약 가능한 시간이 없는 매장을 가능하다고 제시하지 않는다.

## 메뉴·가격·예약금

```bash
ct shop menu tsukiya_shokudo
ct shop policy tsukiya_shokudo --date 2026-10-14 --time 18:00 --person-count 2
```

날짜는 사용자 요청에 맞춘다. `shop menu`의 `.items`만 실제 메뉴 후보이며 `.notices`는 안내 항목이다. `price_status=unknown/notice`나 null 금액을 0원 또는 1원 메뉴로 제시하지 않는다. 매장이 외부 메뉴 공지로 안내하면 링크를 확인하고 출처·게시 시점을 구분한다. `.alcohol_order_required`도 함께 알린다.

예약금은 매장 배지 대신 `shop policy`의 날짜·시간·인원별 `.deposit_status`, `.deposit_total`, `.table_options`, `.refund_policies`를 확인한다. `required`는 일반 예약금 있음·0원 선택지 미제공, `none`은 기본 예약금 0원, `conditional`은 일반 예약금과 캐치페이 0원 결제 선택지가 함께 있음, `selection_required/unknown`은 미확인이다. `.base_deposit_total`을 실제 선결제액으로 단정하지 않는다. `.zero_deposit_option.available=true`이면 카드 등록 후 0원 예약 선택지를 안내하고 취소·노쇼 수수료가 남는다고 설명한다. 사용자별 적용 완료는 공개 조회만으로 확인할 수 없다. `unavailable`과 종료 코드 5는 해당 시간에 자리가 없으며 예약금 여부도 미확인이라는 뜻이다. `--table-type`으로 좌석별 확인이 가능하다. `policy`에는 availability 슬롯의 실제 `.date`·`.time`을 전달한다(25:00 같은 service_time을 쓰지 않음).

이 명령은 공개 GET만 호출하며 임시 좌석 확보나 예약·결제를 하지 않는다. 캐치페이 등 사용자별 최종 청구액은 예약서에서 확인해야 한다. 예약금이 0원이어도 취소 수수료가 없다고 단정하지 않는다.

## 시간 조회와 예약 진행

```bash
ct shop info sushi_hakusha
ct shop availability sushi_hakusha --date 2026-10-18 --person-count 2
ct reserve sushi_hakusha --date 2026-10-18 --time 18:00 --person-count 2
```

`shop availability`는 실제 암호화 시간 조회 API를 사용한다. `available=true`인 슬롯만 가능 시간이다. `service_date`는 영업일이며 자정 이후 시간은 `service_time=25:00`처럼 다음 날을 뜻한다. 사용자에게는 슬롯의 실제 `date`·`time`을 설명하고 CLI 예약 준비에는 `service_time`을 사용한다.

`reserve`는 해당 시간을 다시 조회하고 공식 `booking_url`을 반환한다. **예약을 생성하지 않는다.** `ready_for_browser`와 종료 코드 0도 예약 완료가 아니다. `reservation_created`는 false다. `slot_unavailable`은 종료 코드 5이며 다른 시간을 확인한다.

사용자가 구체적인 예약 진행을 요청하면:

1. 최신 슬롯을 확인하고 반환된 `booking_url`을 사용 가능한 브라우저 도구로 연다. URL만으로 날짜·인원이 반영됐다고 단정하지 말고 보이는 페이지에서 확인한다.
2. 로그인은 사용자의 기존 세션으로 진행한다. 본인 입력이 필요한 인증·OTP가 있으면 해당 단계만 인계한다. 쿠키를 채팅으로 요청하거나 브라우저 내부 저장소를 임의 추출하지 않는다.
3. 메뉴·방문자·예약금·취소 수수료·약관을 실제 화면에서 확인한다. 사용자가 승인한 대상·일시·인원·금액 한도 안에서 진행하고 브라우저 도구의 결제·약관 확인 규칙을 따른다. 예약 시간 클릭도 임시 좌석 확보를 만들 수 있으므로 단순 검색 중에는 클릭하지 않는다.
4. 공식 완료 화면 또는 내 예약 내역에서 식당·일시·인원·예약번호를 확인한 뒤 완료를 보고한다. 불확실한 응답 뒤에는 다시 예약하지 말고 내역부터 확인한다.

현재 직접 예약 생성 API는 구현하지 않았다. 공식 페이지가 빈 화면이거나 로그인에 막히면 예약을 성공했다고 보고하지 않는다. 2026-10-13 재검증에서 Chrome 공식 홈·매장·예약 옵션 화면이 정상 표시됐다. 처음에는 footer만 보였지만 이후 앱 콘텐츠가 나타났다. 초기 스냅샷만으로 지속적인 빈 화면이라고 판단하지 말고 로딩 이후 화면을 확인한다. 근본 원인은 확정되지 않았으며 설정 변경 없이 정상 표시됐다. 실제 로그인·예약 확정은 별도 확인이 필요하다. 매장 첫 화면의 예약금 배지와 선택한 슬롯의 예약금이 다를 수 있으므로 최종 예약 단계의 금액과 환불 규칙을 기준으로 사용자에게 확인한다.

## 로그인과 내 예약

```bash
ct auth status
ct auth status --check
ct auth login
ct reservations list --size 10
```

CLI에서 내 예약을 읽으려면 x-ct-a 세션이 필요하다. `auth login`은 로컬 숨김 프롬프트로 받은 값을 검증하고 Mac 키체인에 저장한다. `--cookie-stdin`도 지원한다. 인증 값을 명령행 인자·로그·문서에 넣지 않는다. 브라우저 로그인과 CLI 인증은 별개이며, 예약을 브라우저로 진행하는 데 CLI 쿠키를 반드시 가져올 필요는 없다.

환경 변수 `CT_SESSION_COOKIE`가 키체인보다 우선한다. 빈 값은 저장된 쿠키 사용도 비활성화한다. `CT_USE_KEYCHAIN=false`로 키체인 사용을 끌 수 있다. 로그인 성공 확인 없이 저장 여부만으로 연결 완료라고 보고하지 않는다.

## 출력과 오류

- JSON 기본값. 검색·추천은 `.items`, 상세는 `.shop`, 날짜는 `.day_slots`, 시간은 `.slots`.
- `--fields`는 snake_case. 원본 `dining`과 `prices` 내부는 서버 필드명을 유지한다.
- 날짜/인원은 예약 시간 조회 조건이며 매장 제외 필터가 아니다. `availableType`만 보지 말고 실제 슬롯을 확인한다.
- 다음 페이지는 `next_cursor`를 동일 조건의 `--cursor`로 전달한다.
- `--dry-run`은 API 무호출이며 지역·shopRef·공개 키 의존 입력을 자리표시자로 보여준다.
- 종료 코드: 0 성공, 1 API/네트워크/응답 오류, 2 입력 오류, 3 인증/권한 오류, 4 상세 성공·날짜 부분 실패, 5 요청 슬롯 없음.
- 코드 4는 상세 JSON과 errors를 보존한다. 알 수 없는 상태는 null/`-`이고 N이 아니다.

상세 CLI 계약은 [README.md](README.md), 이번 준비 결과와 미확인 범위는 [docs/agent-dining-2026-10-12.md](docs/agent-dining-2026-10-12.md)를 필요할 때 읽는다.
