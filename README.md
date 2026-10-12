# CatchTable CLI (ct)

캐치테이블의 매장 검색·추천, 날짜·인원별 예약 시간 확인과 공식 예약 화면 연결을 제공하는 비공식 CLI입니다. Python 3.11 이상이 필요합니다.

## 설치 및 검증

```bash
pip install -e .
# 또는 uv 사용
uv sync
uv run python -m unittest discover -s tests -v
# 원하는 경우 전역 ct 명령 설치/갱신
uv tool install --editable . --reinstall
```

## 에이전트에게 사용하기

이 Mac에는 `catchtable-cli` 스킬을 연결했습니다. 새 채팅에서 “강남에서 일요일 저녁 2명 가능한 식당 추천해줘”, “우래옥 찾아줘”, “이 매장 토요일 2명 빈 시간 확인해줘”처럼 요청할 수 있습니다. 다른 작업 폴더에서는 `uv run --directory /Users/kjlee/Projects/catchtable-cli ct ...`로 실행합니다.

**검색·추천·시간 조회는 일반 실행에서 실제 검증했습니다. 예약은 현재 최신 슬롯 확인과 공식 화면 연결까지 제공합니다. 직접 예약 생성 API는 구현하지 않았으며 예약 확정에는 로그인과 공식 화면의 조건 확인이 필요합니다.** `reserve`의 성공은 예약 완료가 아닙니다. 준비 결과와 남은 제약은 [에이전트 준비 기록](docs/agent-dining-2026-10-12.md)에 있습니다.

```bash
uv run ct doctor
uv run ct search keyword '우래옥' --page-size 5
uv run ct recommend --region '강남' --date 2026-10-18 --person-count 2 --available-only --limit 3
uv run ct shop availability sushi_hakusha --date 2026-10-18 --person-count 2
uv run ct reserve sushi_hakusha --date 2026-10-18 --time 18:00 --person-count 2
```

`recommend`는 실제 검색 첫 페이지(기본 후보 30개)를 평점·리뷰 수로 정렬합니다. 점수는 `(평점×리뷰수+4.0×20)/(리뷰수+20)`이며 고정 가정 4.0점·20개를 공개합니다. `--min-rating`, `--min-reviews`, `--food-kind`, `--candidates`, `--limit`로 조절합니다. `--available-only`는 날짜·인원을 함께 지정해야 하며 서버가 실제 가능 시간을 반환한 후보만 남깁니다. 메뉴 가격 범위와 가격 문구는 `prices`, 선택 이유는 `reasons`에 포함됩니다. 취향·예산에 맞는 최종 선택은 이 근거를 함께 보고 합니다.

`shop availability`는 RSA 암호화를 포함한 실제 시간 조회 API를 호출합니다. 응답 `.slots`의 `available=true`만 가능 시간입니다. `.date`·`.time`은 실제 방문 날짜·시간, `service_date`·`service_time`은 영업일 기준입니다. 예를 들어 `service_time=25:00`은 다음 날 01:00이며 `reserve --time`에는 이 값을 넣습니다. 시각이 지나면 좌석 상태가 바뀔 수 있습니다.

`reserve`는 다시 시간 조회 후 `booking_url`을 반환합니다. `reservation_created=false`이며 실제 좌석 확보·예약·결제는 발생하지 않습니다. 공식 화면에서 날짜·인원·메뉴·예약금·취소 조건을 확인하고 확정해야 합니다. 슬롯이 사라지면 `slot_unavailable`, 종료 코드 5를 반환합니다. 완료 화면이나 내 예약 내역을 확인해야 실제 예약 완료입니다.

## 메뉴와 예약금 조회

```bash
ct shop menu tsukiya_shokudo
ct shop menu Z-JIC_pangyo --format table
ct shop policy tsukiya_shokudo --date 2026-10-14 --time 18:00 --person-count 2
ct shop policy Z-JIC_pangyo --date 2026-10-14 --time 19:00 -p 2 --table-type H
ct schema show 'shop policy'
```

두 명령 모두 공개 GET 조회만 합니다. 로그인·좌석 확보·예약 생성·결제는 하지 않으며 `--dry-run`, JSON/table/compact 출력을 지원합니다. 날짜는 사용자가 원하는 실제 방문 날짜로 바꿉니다. `shop policy`의 시간은 **실제 방문 시각 00:00~23:59**입니다. `availability`의 실제 `.date`·`.time`을 사용하세요(영업일 기준 `25:00` 입력은 거부).

`shop menu`는 메뉴 카테고리를 펼쳐 `.items`로 출력하고, 공지·인스타그램 참조 같은 안내 항목은 `.notices`로 분리합니다. 가격은 `price_min`·`price_max`(원), 원본은 `source_price_min`·`source_price_max`입니다. 누락·0원·1원·안내용 가격은 실제 판매가로 단정하지 않고 null/unknown 또는 notice로 표시합니다. 메뉴판 이미지 URL, 최종 수정일, 주류 필수 여부도 제공합니다. 다른 사이트의 가격은 CLI 결과에 섞지 않습니다.

`shop policy`는 `/api/reservation/v1/dining/reservation-options`를 날짜·시간·인원으로 조회합니다. `DEPOSIT_PER_MAN`의 기본 예약금은 **min(인당 예약금 × 인원, 상한금액)**이며 좌석별 `.table_options`로 분리합니다. `--table-type`은 응답을 필터링합니다. 메뉴 구매·추가상품·서로 다른 옵션은 확정 금액을 추측하지 않습니다.

| deposit_status | 의미 | deposit_required / deposit_total |
| --- | --- | --- |
| required | 일반 예약금 있음, 0원 선택지 미제공 | true / 원 단위 합계 |
| conditional | 일반 예약금은 있으나 캐치페이 0원 결제 선택지 제공 | null / null |
| none | 명시적인 빈 예약 메뉴 또는 0원 기본 예약금 | false / 0 |
| selection_required | 메뉴·좌석·추가상품 선택 필요 | null / null |
| unknown | 필드 누락·새로운 타입 등으로 금액 확인 불가 | null / null |
| unavailable | 해당 시간/좌석 예약 불가 | null / null, 종료 코드 5 |

`base_deposit_total`은 일반 예약금, `zero_deposit_option.available`은 매장의 캐치페이 0원 결제 지원 여부입니다. `upfront_amount=0`은 이 선택지를 적용했을 때의 선결제액이며 사용자별 적용 완료를 뜻하지 않습니다. 카드 등록이 필요하고 취소·노쇼 수수료는 별도로 남습니다.

`ok=true`는 조회 성공이며 `unknown`일 때 예약금이 없다는 뜻이 아닙니다. `refund_policies`는 서버가 준 환불율을 백분율로 표시합니다. `reservation_penalty_available`·`cancellation_charges`는 원본 옵션 근거이며, 이 플래그만으로 캐치페이 가입·카드 등록·취소 수수료 면제를 단정하지 않습니다. 예약금 0원이어도 취소 수수료가 있을 수 있고, 로그인·메뉴·할인·캐치페이 선택 후 최종 청구액은 공식 예약서에서 확인해야 합니다.

실제 검증 예: 츠키야 2026-10-14 18시 2명은 일반 예약금 1만원과 캐치페이 0원 결제 선택지가 함께 있어 `conditional`, 같은 날 19시는 unavailable. 메즈클라 19시 2명은 기본 예약금 0원, 지직 19시 2명은 일반 예약금 2만원과 0원 선택지가 있어 `conditional`입니다. 상세 근거는 [메뉴·예약금 검증 기록](docs/menu-policy-2026-10-13.md)을 참고하세요.

## 로그인과 내 예약

공개 검색·추천·시간 조회는 로그인 없이 가능합니다. 내 예약을 조회하려면 CLI 세션이 필요합니다.

```bash
ct auth status             # 저장 여부; 서버 검증 아님
ct auth login              # 숨김 프롬프트에서 x-ct-a 값 입력 → 서버 검증 → OS 저장소 저장
ct auth status --check     # 실제 로그인 유효성 확인
ct reservations list --size 10
ct auth logout             # CLI에 저장한 세션만 삭제
```

`auth login`에는 공식 사이트에 로그인한 본인의 `x-ct-a` 쿠키 값만 넣습니다. Cookie 헤더 전체를 넣지 않습니다. 이 값은 계정 접근 권한이므로 채팅·스크린샷·명령행 인자·공유 문서에 붙여 넣지 마세요. 로컬 숨김 프롬프트 또는 신뢰할 수 있는 입력의 `--cookie-stdin`을 사용합니다. Mac에서는 키체인, Windows에서는 Credential Manager, Linux에서는 Secret Service를 사용하며 평문 파일로 폴백하지 않습니다. 현재 검증에서는 실제 로그인 세션이 없어 저장·내역 조회는 대체 응답 테스트만 수행했습니다.

브라우저 세션과 CLI 세션은 별개입니다. CLI에 쿠키를 가져오지 않아도 로그인한 공식 브라우저에서 예약할 수 있습니다. `reservations list`는 예정 예약(PLANNED)을 조회하며 다음 페이지는 `data.scrollKey`를 `--cursor`로 전달합니다. 예약 생성·취소는 하지 않습니다.

## 사용 예제

```bash
# 자동완성 (매장 목록 검색과 다른 명령)
ct search search "스시" --limit 2 --fields label,item_type,code

# 지역별 매장 목록
ct search region --region "강남" --page-size 3
ct search region --region "부산" --sort REVIEW --format table

# 음식 코드는 자동완성 FOOD_KIND 항목의 code를 사용
ct search region --region "강남" --food-kind E_31

# 날짜·인원별 예약 정보를 함께 조회
ct search region --region "강남" --visit-date 2026-10-17 --person-count 2

# 두 번째 조회부터는 직전 응답의 next_cursor를 그대로 사용
ct search region --region "강남" --page-size 3 --cursor '<next_cursor>'

ct shop info bornandbredoriginal
ct shop info bornandbredoriginal --format compact
ct shop info bornandbredoriginal --params 'personCounts=2'

ct schema list
ct schema show 'search region'
ct search region --region "강남" --dry-run
```

지역명은 서버 지역 목록의 `name`, `displayName`, `code`와 정확히 일치해야 합니다. 예를 들어 강남은 `CAT011001`, 부산은 `CAT026`으로 해석됩니다. 여러 코드에 해당하거나 지역을 찾지 못하면 검색을 중단합니다.

날짜·인원은 **예약 정보 조회 조건**입니다. 예약 가능한 매장만 남기는 필터가 아닙니다. 응답 `items[].dining.singleDateSlotInfo`의 날짜, 인원, 시간 목록을 확인하세요. 시간 목록이 비어 있으면 `availableType`만으로 예약 가능하다고 판단하면 안 됩니다. `--person-count`는 양수이며 `--visit-date`와 함께 사용합니다.

정렬은 `RATING`(별점), `REVIEW`(리뷰 수), `RECOMMENDED`(추천)를 지원합니다. 기준 좌표 없는 `DISTANCE`는 오류로 처리합니다. 검증되지 않은 `--category`와 숫자 페이지 `--page`는 제거했습니다. 페이지 이동은 같은 조건과 크기를 유지하며 `--cursor`를 사용합니다. `next_cursor: null`이면 다음 페이지가 없습니다.

## 출력 계약

조회 결과의 공통 필드는 정규화된 snake_case를 사용합니다. `prices`, `dining`, `reservations list.data` 내부는 서버 필드명을 유지합니다. JSON은 stdout, 표와 오류는 stderr, compact는 stdout의 TSV입니다.

| 명령 | JSON 구조 |
| --- | --- |
| `search search` | `ok`, `items`, `total`, `returned`, `suggestions` |
| `search keyword`, `search region` | `ok`, `region_code`, `items`, `total`, `returned`, `next_cursor` |
| `shop info` | `ok`, `partial`, `alias`, `shop_ref`, `shop`, `day_slots_status`, `day_slots`, `errors` |

`--fields`는 모든 출력 형식에서 자동완성 항목, 검색 매장 또는 상세 매장 필드를 선택합니다. 잘못된 필드명은 요청 전에 거부합니다. 상세 조회에서는 날짜 목록과 부분 실패 정보가 유지됩니다. 필드 목록은 `ct schema show '<명령>'`의 `field_model`에서 확인할 수 있습니다.

자동완성의 `--limit`는 모든 형식에서 `items`에 적용됩니다. `total`은 서버가 준 제안 수, `returned`는 출력한 수입니다. 추가 키워드 `suggestions`는 `--suggest` 사용 시 결과가 비었을 때 별도 요청 1회로 가져오며 최대 5개입니다. 지역 검색의 `--page-size`는 서버 페이지 크기입니다.

```bash
ct search region --region "강남" | jq '.items[] | select(.avg_rating >= 4.5) | .shop_name'
ct search search "스시" --limit 2 | jq '.items[].label'
ct shop info bornandbredoriginal | jq '.day_slots[] | {visit_yymmdd,status_code,is_available}'
```

### 예약 날짜 상태

`availableStatus`는 `status_code`, `availablePersonCounts`는 `available_person_counts`에 반영됩니다. 날짜는 `visit_yymmdd`에 ISO 날짜로 출력됩니다.

| API 상태 | 의미 | is_available / 표·간략 출력 |
| --- | --- | --- |
| AVAILABLE | 예약 가능 | true / Y |
| DAY_OFF | 휴무 | false / N |
| CLOSED | 예약 마감 | false / N |
| BEFORE_OPEN | 예약 오픈 전 | false / N |
| PHONE_INQUIRY | 전화 문의 필요 | null / - |
| 미확인·새로운 상태 | 알 수 없음 | null / - |

API가 명시적인 `isAvailable`을 주면 그 값을 우선합니다. `day_slots_status`의 `ok`는 날짜 조회 성공, `empty`는 날짜 정보 없음, `error`는 조회 실패입니다. 정보가 없는 상태와 예약 불가를 구분합니다. 날짜별 상태는 특정 인원·시간의 예약을 보장하지 않습니다.

## 요청 직접 전달과 dry-run

검색 명령의 `--json-body`는 **본문 전체를 대체**합니다. 자동완성은 문자열 `query`가 필수이며 추가 필드도 그대로 전달됩니다. 지역 검색은 이 옵션을 사용하면 지역명 해석과 일반 검색 옵션의 본문 구성을 생략합니다. `--region`은 명령 인자로 여전히 필요하지만 실제 필터는 JSON에 명시해야 합니다.

```bash
ct search search "한우" --json-body '{"query":"한우","type":"SHOP"}' --dry-run
ct search region --region "부산" --json-body '{"filters":{"displayRegionCodes":["CAT026"]},"sort":{"sortType":"review_count"},"paging":{"offset":"0","size":3},"listType":"GENERAL","divideType":"NON_DIVIDE"}'
```

`--params 'key=value,key2=value2'`는 HTTP 쿼리 파라미터를 전달합니다. JSON 본문의 검색 필터를 변경하는 옵션이 아닙니다. 임의 필드의 서버 지원을 보장하지 않으며, 알려진 본문 필드의 타입·날짜·양수 조건을 검증합니다. 예전 최상위 `region`, `visitDate`, `sortMethod` 등은 무시되는 문제를 막기 위해 거부합니다.

`shop info`는 GET 요청이므로 `--json-body`가 없습니다. `--params`는 예약 날짜 조회에만 전달되며 `shopRef` 변경은 거부합니다. 쉼표는 파라미터 구분자라 값 안에 쓸 수 없습니다.

`--dry-run`은 네트워크를 호출하지 않습니다. 실행과 같은 요청 빌더로 메서드·경로·본문·파라미터를 출력합니다. 지역 검색은 지역 목록 조회 후 코드 확정, 매장 상세는 상세 조회 후 shopRef 확정이 필요하므로 후속 요청의 값은 명시적인 자리표시자로 표시합니다.

## 종료 코드

| 코드 | 의미 |
| --- | --- |
| 0 | 성공 |
| 1 | API·네트워크·응답 형식 오류 또는 미구현 명령 |
| 2 | 입력·명령·옵션 오류 |
| 3 | 인증·권한 오류 (HTTP 401/403 등) |
| 4 | 매장 상세는 성공했으나 예약 날짜 조회는 실패 |
| 5 | 요청한 예약 시간을 현재 확인할 수 없음 |

종료 코드 4에서는 성공한 상세 데이터와 `partial: true`, `errors`가 JSON에 남고 stderr에도 실패 원인이 출력됩니다. 코드 5는 예약 미생성 상태와 슬롯 없음 JSON을 반환합니다. 그 외 실패에서는 stdout에 성공 결과를 출력하지 않습니다.

## 환경 변수

| 변수 | 설명 | 기본값 |
| --- | --- | --- |
| `CT_SESSION_COOKIE` | `x-ct-a` 인증 쿠키; 설정 시 키체인보다 우선 | 미설정이면 키체인 조회 |
| `CT_USE_KEYCHAIN` | OS 저장소의 CLI 쿠키 사용 | true |
| `CT_USE_CURL_CFFI` | curl_cffi 전송 사용, 연결 실패 시 httpx 폴백 | true |
| `CT_API_BASE_URL` | API 기본 주소 | https://ct-api.catchtable.co.kr |

셸 환경 변수로 설정합니다. `CT_SESSION_COOKIE`를 명시적으로 빈 값으로 설정하면 키체인 쿠키도 사용하지 않습니다. OS 저장소 쿠키는 기본 공식 API 주소에만 자동으로 적용합니다. `.env` 자동 로딩과 `CT_LOG_LEVEL`은 구현되어 있지 않습니다.

## 호환성 및 검증 범위

이번 수정부터 필드 선택 여부와 무관하게 정규화된 JSON을 출력합니다. 기존 원본 응답의 `.data.suggestions` 또는 `.data.shopResults.shops`를 읽던 스크립트는 `.items`로 변경해야 합니다. `shop`도 원본 API envelope 대신 정규화된 상세 객체입니다. 숫자 페이지 이동은 커서 방식으로 변경되었습니다.

`reserve`는 공식 예약 화면으로 이어주는 준비 명령입니다. 직접 예약 생성과 빈자리 알림 등록(`notify`)은 미구현입니다. `notify`는 종료 코드 1입니다. 초기 검색 수정 기록은 [검증 기록](docs/verification-2026-10-12.md), 이후 기능 확장과 현재 상태는 [에이전트 준비 기록](docs/agent-dining-2026-10-12.md)을 참고하세요.

## HTTPS 인증서

httpx는 `truststore.SSLContext`로 OS 신뢰 저장소를 사용합니다. 일반 `uv run ct ...`에서 별도 주입 없이 동작합니다. `SSL_CERT_FILE`/`SSL_CERT_DIR`를 명시하면 해당 CA 설정을 우선하며, 파일 오류를 무시하거나 시스템 루트로 우회하지 않습니다. 인증서 검증과 호스트명 검증은 항상 유지합니다.

기본 curl_cffi 전송이 실패하면 공개 조회 요청에 한해 httpx로 전환하고 같은 클라이언트에서는 재사용합니다. 쓰기 요청은 실패 후 다른 전송으로 자동 재전송하지 않습니다. 문제가 생기면 `ct doctor`로 확인하세요.

---

## License

Distributed under the **MIT License**. See `LICENSE` for more information.

---

## 조각 사유 (Purpose & Motivation)

본 프로젝트는 캐치테이블(CatchTable)의 공식 API 또는 SDK가 부재한 환경에서, **AI 에이전트 친화적 CLI 설계(Agent DX) 연구** 및 개인 생산성 향상을 목적으로 개발되었습니다.

- 공식 API/SDK 부재로 인한 CLI 기반 자동화 수요 충족
- Agent DX(Developer Experience for Agents) 7대 원칙 검증을 위한 실험적 구현체
- 개인 학습 및 연구 목적의 비상업적 프로젝트

## 면책사항 (Disclaimer & Legal Notice)

> **이 프로젝트를 사용하기 전에 반드시 아래 내용을 숙지하십시오.**

### 비공식 도구

본 프로젝트는 **캐치테이블(CatchTable) 및 주식회사 와드컴퍼니와 어떠한 제휴, 후원, 보증, 공식적 관계도 없는 독립적인 비공식 도구**입니다. "캐치테이블", "CatchTable" 및 관련 상표는 주식회사 와드컴퍼니의 자산이며, 본 프로젝트에서의 사용은 식별 목적에 한합니다.

### 이용약관 준수 책임

본 도구의 사용은 **전적으로 사용자의 책임**입니다. 사용자는 캐치테이블 서비스 이용약관(Terms of Service)을 반드시 확인하고 준수해야 합니다. 본 도구의 사용이 서비스 이용약관에 위반될 수 있으며, 이로 인한 **계정 정지, IP 차단, 법적 조치 등 모든 결과에 대한 책임은 전적으로 사용자에게 있습니다.**

### 무보증 (AS-IS)

본 소프트웨어는 **"있는 그대로(AS-IS)" 제공**되며, 명시적이든 묵시적이든 어떠한 종류의 보증도 하지 않습니다. 여기에는 상품성, 특정 목적에의 적합성, 비침해에 대한 묵시적 보증이 포함되나 이에 한정되지 않습니다.

### 서비스 변경 및 중단

본 도구는 비공식 API 엔드포인트에 의존하므로, **캐치테이블의 API 변경, 보안 정책 강화, 서비스 구조 변경 등에 의해 언제든지 작동이 중단될 수 있습니다.** 이에 대한 지속적인 유지보수나 호환성을 보장하지 않습니다.

### 과도한 사용 금지

과도한 요청(rate limit 초과, 대량 크롤링, 자동화된 반복 요청 등)은 서비스 장애를 유발할 수 있습니다. **이로 인한 서비스 차단, 법적 책임, 제3자 피해에 대한 모든 책임은 사용자에게 있습니다.** 합리적인 사용 범위 내에서만 사용하십시오.

### 데이터 및 개인정보

본 도구를 통해 수집되는 데이터의 저장, 처리, 공유에 대한 책임은 전적으로 사용자에게 있습니다. 개인정보보호법 등 관련 법규를 준수해야 하며, 수집 데이터의 상업적 이용은 관련 법률 및 서비스 이용약관에 따라 제한될 수 있습니다.

### 손해배상 면책

본 프로젝트의 개발자는 본 도구의 사용 또는 사용 불가능으로 인해 발생하는 **직접적, 간접적, 부수적, 특별, 결과적 또는 징벌적 손해**에 대해 어떠한 경우에도 책임지지 않습니다. 이는 데이터 손실, 이익 손실, 사업 중단, 계정 정지, 서비스 차단 등을 포함하나 이에 한정되지 않습니다.

### 용도 제한

본 도구는 **개인적인 연구, 학습, 생산성 향상 목적**으로만 제작되었습니다. 상업적 목적의 대량 데이터 수집, 서비스 방해, 경쟁 서비스 구축, 또는 캐치테이블의 비즈니스에 손해를 끼치는 용도로 사용하는 것을 금합니다.
