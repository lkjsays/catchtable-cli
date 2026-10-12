# 메뉴·예약금 CLI 확장 검증 — 2026-10-13 KST

## 구현과 근거

- `ct shop menu ALIAS`: GET `/api/display/v2/shops/{alias}/tabs/menu`. 응답은 data envelope가 없는 형태도 지원. category.items를 펼치고 가격과 안내 항목을 구분.
- `ct shop policy ALIAS --date YYYY-MM-DD --time HH:MM -p N`: 매장 shopRef 조회 후 GET `/api/reservation/v1/dining/reservation-options`에 date YYMMDD, time HHmm, personCount 전달.
- 공개 공식 웹앱 20261008152819 `bootstrap.js`의 `getReservationOptions`, `getDisplayShopMenuInfo`, `getDiningReservationRefundPolicyTerm`과 실제 응답으로 계약 확인. 환불 baseDay -1=노쇼, 0=당일, 양수=방문 며칠 전. refundRate 0~1 → 백분율.
- 날짜/시간/인원별 옵션만 읽음. holdings/form/create/payment 요청 없음. CLI 인증값·브라우저 쿠키 추출 없음.
- 기본 예약금은 DEPOSIT_PER_MAN의 인당 금액×인원에 maxAmount 상한 적용. 명시적 빈 menuSets는 기본 예약금 0원. 필드 누락/새 타입/추가상품/메뉴 구매는 unknown 또는 selection_required.
- `hasEmptySlot=false`는 unavailable, 금액 null, 종료 코드 5. 자리가 없는데 예약금 0원이라고 표시하지 않음.
- 일반 예약금과 캐치페이 0원 결제 선택지를 구분. 공식 웹앱은 reservationOptions.reservationPenaltyAvailable을 isDepositFreeShop으로 사용. 이 값이 true이면 0원 결제 선택지를 제공하지만 사용자별 카드 등록·적용 여부나 무료취소를 추론하지 않음.

## 실응답 회귀 사례

| 매장 | 요청 | 결과 |
| --- | --- | --- |
| 츠키야 | 10/14 18:00 2명 | 바 좌석, 일반 예약금 1만원 + 캐치페이 0원 결제 선택지 → conditional |
| 츠키야 | 10/14 19:00 2명 | hasEmptySlot=false → unavailable |
| 지직 판교 | 10/14 19:00 2명 | 홀·바 일반 예약금 2만원 + 캐치페이 0원 선택지 → conditional |
| 메즈클라 | 10/14 19:00 2명 | 빈 menuSets → 기본 예약금 0원 |

츠키야 환불율: 노쇼 0%, 당일 20%, 1일 전 50%, 2일 전 100%. **앞선 “예약금 없는 후보로는 조건에 맞지 않음” 판단은 철회.** 일반 예약금과 0원 결제 선택지를 혼동한 오류였음.

메뉴 실응답: 츠키야는 `인스타그램 참조 (@tsukiya_shokudo)`라는 항목에 minPrice="1"만 등록. 실제 가격은 unknown으로 반환하며 원문을 notices로 보존. 주류 주문 필수, 콜키지 안내는 주종 무관 테이블당 최대 1병. 최종 메뉴 수정일 응답 2026-02-22. 지직의 실제 메뉴 항목은 카테고리와 정가(오마카세 1인 24,000원 등)를 정상 파싱.

## 츠키야 메뉴 조사

[공식 Instagram](https://www.instagram.com/tsukiya_shokudo/)의 현재 공개 게시물에서 점다랑어 와라야끼, 우니 방어 이소베마끼, 카이센 타르타르, 고등어 타르틴, 사시미 나가이모 아에, 이달의 하루마키, 밤 티라미슈를 확인. 가격은 게시되지 않아 최신 가격 확정 불가.

- [점다랑어 와라야끼](https://www.instagram.com/tsukiya_shokudo/p/DeL7YlDzIy1/)
- [우니 방어 이소베마끼](https://www.instagram.com/tsukiya_shokudo/p/DeL7J1vzwcq/)
- [10월 휴무](https://www.instagram.com/tsukiya_shokudo/p/DeIdieYTmcr/): 일요일 및 10/12~13 휴무, 다른 공휴일 정상 영업 안내.

[뽈레 메뉴 목록](https://polle.com/place/4HmA78/츠키야)은 숙성 사시미 한접시 36,000원, 후토마키 20,000원, 전복 내장 크림 파스타 21,000원, 수제 교자 8,000원 등을 표시. 최신 공식 메뉴와 다를 수 있는 외부 등록가이며 현재 판매·가격을 보장하지 않음. CLI 응답에는 이 외부 정보를 섞지 않음.

## 테스트

실응답을 줄인 공개 fixture로 팀 상한/인당 예약금/0원/자리 없음/좌석별 차이/새 타입/누락/메뉴선택·추가상품, 안내 가격, category 메뉴 파싱, 날짜·시간 검증, dry-run 무호출, GET-only 실행, 스키마 및 JSON/table/compact 출력을 검증.

검증 완료: 프로젝트 및 전역 editable CLI Python 환경에서 각각 57개 unittest 통과. Ruff F/I, formatter, git diff --check 통과. `/tmp` 작업 폴더에서 일반 `/Users/kjlee/.local/bin/ct` 실행으로 위 4개 정책 사례와 지직 메뉴 31개 반환 재확인.

## 0원 배지 불일치 정정

사용자 스크린샷 지적 후 공식 츠키야 상세의 “예약금 0원” 도움말을 읽음. 미리 예약금을 지불하지 않는 서비스이며 캐치페이 카드 등록이 필요하고 취소·노쇼 수수료는 등록 카드로 결제된다는 안내를 확인. 예약 버튼/슬롯/약관은 조작하지 않음. [공식 화면 근거](tsukiya-zero-deposit-2026-10-13.jpg).

CLI는 base_deposit_total=10000, zero_deposit_option.available=true/upfront_amount=0/requires_catchpay_card=true, deposit_status=conditional, deposit_total=null, deposit_required=null을 반환하도록 수정. 각 좌석도 같은 의미로 출력. menu_options의 deposit_total은 일반 예약 메뉴 설정 금액. 공개 옵션은 사용자별 실제 적용을 확인하지 않으므로 user_eligibility_verified=false. 0원 지원 플래그 누락은 unknown, 자리 없음은 unavailable 유지.

추가 회귀 검증: 일반 예약금과 0원 선택지 동시 존재, 명시적 미지원, 플래그 누락/잘못된 형식, 자리 없음, JSON/table/compact 표시. 전체 58 tests 통과. 일반 전역 ct에서 츠키야 18시 2명 conditional 실응답 재확인.


## 마지막 시간 재조회

2026-10-13 01:41:47 KST 일반 `ct shop availability tsukiya_shokudo --date 2026-10-14 --person-count 2`: 17:00·18:00 available=true 반환. 19시 전후 다른 슬롯은 반환되지 않음. 예약·결제는 실행하지 않음.
