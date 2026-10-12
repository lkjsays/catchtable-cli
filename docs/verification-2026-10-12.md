# 수정 검증 기록 — 2026-10-12 (Asia/Seoul)

> 이 문서는 초기 수정 시점의 기록입니다. 이후 인증서 오류를 해결했고 추천·시간 조회·예약 준비 기능을 추가했습니다. 현재 상태는 [후속 기록](agent-dining-2026-10-12.md)을 보세요. 아래의 기본 실행 인증서 제약은 후속 수정에서 해소됐습니다.

## API 계약 근거

인증 쿠키 없이 공개 웹앱의 배포 코드와 실제 조회 응답을 비교했다.

- 웹앱: https://app.catchtable.co.kr/
- 확인한 배포 코드: https://app.catchtable.co.kr/static/app/real/20261008152819/assets/bootstrap.js
- 지역 목록: `GET /api/v4/filters/ct-region-filter`, `data.ctRegions`의 이름·코드·하위 지역.
- 검색: `POST /api/v7/search/list`. `filters.displayRegionCodes`, `filters.foodKindCodes`, `sort.sortType`, `reservationParams`, `paging.offset/size` 사용.
- 웹앱의 `useListRequestParams`와 `postSearchList`가 위 계약을 사용한다. 기존 CLI의 최상위 `region`, `foodKindCode`, `sortMethod`, `visitDate`는 이 계약과 달랐다.
- 웹앱의 `getSlotAvailablityDisplayText`는 AVAILABLE=예약 가능, PHONE_INQUIRY=전화 문의, DAY_OFF=휴무, CLOSED=예약 마감, BEFORE_OPEN=오픈 전으로 해석한다.

지역 코드는 코드에 하드코딩하지 않고 매 실행 서버 목록에서 해석한다. dry-run에서는 네트워크 없이 이 의존 관계와 자리표시자를 보여준다.

## 실제 결과 비교

동일한 페이지 크기 3으로 조회했다. 아래 수치와 순서는 확인 시점의 관측값이다.

| 조건 | 관측 결과 |
| --- | --- |
| 강남 / CAT011001 / 별점 순 | 1,825건. 스시하쿠샤(삼성), 타쿠(압구정), 시드니 서울(청담) |
| 부산 / CAT026 / 별점 순 | 2,101건. 스시이마(부산 마린시티), 오스테리아윤(부산 광안리), 글라스앤보틀(부산 연산) |
| 강남 + 음식 코드 E_31 | 140건으로 감소. 스시하쿠샤, 타쿠, 스시이담 청담점 |
| 강남 / 리뷰 순 | 비놀릭(10,148), CHOI. 쵸이닷(7,001), 조선팰리스 콘스탄스(6,963)로 순서 변경 |
| 강남 두 번째 커서 | 무쇠김치삼겹 선릉점, 블러프, 스시이담 청담점. 첫 페이지와 중복 없음 |

숫자 offset=3은 HTTP 500을 반환했다. 서버의 `paging.nextOffset` 문자열을 그대로 전달하면 다음 결과를 받았다. 이에 `--page`를 제거하고 `--cursor`를 제공한다. 추천 정렬의 `recommended` 값은 웹앱 계약에서 확인했으나 추천 순위의 품질은 평가하지 않았다.

날짜와 인원은 매장 제외 필터가 아니었다. 같은 스시하쿠샤의 응답에서:

- 날짜 미지정: `multipleDatesSlotInfo.dailySlotList`가 반환된다.
- 2026-10-17 / 4명: `singleDateSlotInfo.personCount=4`, `timeSlotList=[]`.
- 2026-10-17 / 1명: `12:00` 시간 1건.
- 2026-10-18 / 1명: `12:00`, `18:00` 시간 2건.

따라서 날짜·인원 변경이 실제 예약 시간 응답에 반영됨을 확인했으며, `availableType=AVAILABLE`만으로 빈 시간 목록을 예약 가능하다고 해석하지 않는다. 검색 출력에 `dining`을 유지한다.

수정된 CLI의 실제 실행도 확인했다:

- 강남 compact, 부산 table: 위 지역에 맞는 결과, 종료 코드 0.
- 자동완성 JSON `--limit 2 --fields label,item_type`: 정확히 2건, `item_type=FOOD_KIND` 보존.
- `shop info bornandbredoriginal` JSON·compact: 본앤브레드 오리지널, 날짜 14건, DAY_OFF/CLOSED와 N 일치, 종료 코드 0.
- 모르는 상태, 전화 문의, 부분 조회 오류는 합성 응답 회귀 테스트로 검증했다. 실서비스 장애를 유발하지 않았다.

## 자동 검증

```bash
uv run python -m unittest discover -s tests -v
```

22개 테스트 통과. 입력 오류 하위 사례는 실제 실행·dry-run 양쪽에서 검사한다.

- 날짜·인원·JSON 객체/필드 타입·잘못된 필드명·제거된 옵션을 요청 전에 거부.
- 지역 이름을 코드로 해석, 해석 실패 시 검색 요청 중단.
- 모든 출력 형식의 자동완성 제한·필드 선택, 날짜 상태 일관성.
- raw 본문/쿼리 파라미터 전달, 실제 HTTP 전송 계층까지 확인.
- dry-run 무호출과 실행 요청 비교. 지역 코드/shopRef 자리표시자 치환 후 일치.
- 조회 실패·정보 없음·예약 불가 구분, 부분 실패 출력과 종료 코드 4.
- API/HTTP/입력 오류 종료 코드 및 도움말과 스키마의 옵션 일치.

`tests/fixtures/`는 실제 응답에서 필요한 공개 필드만 추렸다. 초기 재현 자료의 2026-10-11 날짜 응답과 이번 2026-10-12 검색 응답을 포함한다. 미확인 상태 등은 테스트 내부 합성 사례다.

## 환경 제약과 미확인 범위

현재 Mac의 새 uv Python 환경에서는 기본 curl_cffi/httpx 인증서 검증이 `CERTIFICATE_VERIFY_FAILED`로 실패했다. 시스템 curl은 검증을 유지한 채 성공했다. 원인은 신뢰 저장소 차이로 추정하며 시스템 설정은 바꾸지 않았다.

수정된 CLI의 위 실시간 실행 검증에는 임시 `uv run --with truststore` 환경에서 `truststore.inject_into_ssl()`로 시스템 신뢰 저장소를 사용하고 `CT_USE_CURL_CFFI=false`, `CT_SESSION_COOKIE=''`를 설정했다. 인증서 검증을 끄지 않았다. 이 조치는 저장소 의존성이나 기본 실행 방식에 반영하지 않았으므로 **현재 환경의 일반 `uv run ct ...` 네트워크 조회에는 인증서 문제가 남아 있다.** 테스트·dry-run에는 영향이 없다.

인증이 필요한 기능, 예약 생성, 알림 등록은 실행하지 않았다. 계정 상태를 변경하지 않았다. 임의 raw 필드의 서버 지원, 모든 지역·음식 코드·상태 조합은 보장하지 않는다. 상세 날짜 정보는 실제 예약의 성공 보장이 아니다.

임시 전체 실행 로그: `/tmp/ct-fix-verification/`. 임시 경로가 사라져도 위 요약과 저장소 회귀 데이터로 확인 범위를 알 수 있다.
