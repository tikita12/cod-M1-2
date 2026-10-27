# 실제 배포 실행 증빙

검증일: 2026-10-27. 실제 배포 URL의 응답과 로컬에 기록한 클라우드 검증 결과를 정리했습니다. 모의 테스트 결과를 실제 응답처럼 사용하지 않았습니다. 인증키·서비스 계정 JSON·개인 대화는 포함하지 않습니다.

## 배포 접속과 Swagger

- 프론트: https://cod-m1-2-frontend.vercel.app
- 백엔드: https://geogyfood.onrender.com
- Swagger: https://geogyfood.onrender.com/docs
- 캡처 환경: Windows, 설치된 Chrome의 헤드리스 모드. 데스크톱 1440×1000, 모바일 폭 390×844 CSS 픽셀.
- 아래 health·OpenAPI 응답 수집 시각: 2026-10-27 11:25 UTC (20:25 KST).

실제 응답 본문:

```http
GET https://geogyfood.onrender.com/health
HTTP 200
{"status":"ok","storage":"firestore","firestore_configured":true}
```

실제 OpenAPI 응답에서 필요한 필드만 발췌했습니다. `paths`는 실제 경로 목록이며 전체 스키마를 복사한 것은 아닙니다.

```text
GET https://geogyfood.onrender.com/openapi.json → HTTP 200
openapi: 3.1.0
info.title: 농산물 가격 분석 API
info.version: 0.1.0
paths:
  /health
  /health/ready
  /api/data/catalog
  /api/data/summary
  /api/data
  /api/data/trend
  /api/data/{record_id}
  /api/chat/status
  /api/chat
  /api/conversations
  /api/conversations/{conversation_id}
```

![실제 Swagger 화면](../docs/images/swagger.png)

## 실제 가격 CRUD 검증

검증 시작: 2026-10-27 10:49 UTC (19:49 KST). 대상 서버: `https://geogyfood.onrender.com`.
고유한 테스트 품종명으로 임시 가격 1건을 생성하고, 해당 ID만 수정·조회·삭제했습니다. 기존 가격을 수정하지 않았습니다.

테스트 문서 ID:
`c6b6486fa6050e79da52142ebca60bf95c6dee7558f24a997889d221b3bb3fb3`

요청 조건: 2024-11, 감자, 상품, 1kg, 가격 123원. 수정 요청은 `{"average_price":124,"note":"Temporary verification updated"}`입니다. 인증 헤더 값은 제외했습니다.

아래는 실행 당시 저장한 검사 로그의 상태 코드·검증값입니다. 전체 HTTP 응답 본문을 보존한 것처럼 재구성하지 않았습니다.

| 실제 요청/검사 | 실제 결과 |
| --- | --- |
| 시작 revision 읽기 | 8 |
| `POST /api/data` | 201, 응답 ID가 계산한 테스트 ID와 일치 |
| 등록 후 revision 읽기 | 9 |
| 같은 자료로 `POST /api/data` | 409, 중복 거절 |
| 실패 후 revision 읽기 | 9 유지 |
| `PATCH /api/data/{테스트 ID}` | 200, 응답 `average_price`가 `"124"`인지 검사 통과 |
| `GET /api/data/{테스트 ID}` | 200, 저장된 `average_price`가 `"124"`인지 검사 통과 |
| 수정 후 revision 읽기 | 10 |
| `DELETE /api/data/{테스트 ID}` | 204 |
| 삭제 후 `GET /api/data/{테스트 ID}` | 404, 테스트 기록 정리 확인 |
| 최종 캐시 revision 확인 | 11 |

실행 로그 발췌:

```json
[
  {"check":"create","status":201,"passed":true},
  {"check":"duplicate_rejected","status":409,"passed":true},
  {"check":"failed_create_preserves_revision","revision":9,"passed":true},
  {"check":"update","status":200,"passed":true},
  {"check":"read_updated_record","status":200,"passed":true},
  {"check":"delete_test_record","status":204,"passed":true},
  {"check":"confirm_deleted","status":404,"passed":true}
]
```

실제 검증 중 전체 스트림 조회가 `503 / firestore_timeout`으로 실패했습니다. 이를 숨기지 않고 500건 단위 페이지 조회로 수정한 뒤 실제 Firestore 자료로 캐시를 복구했습니다. CSV seed는 실행하지 않았습니다.

```json
{
  "check":"paginated_rebuild",
  "revision":11,
  "records":14131,
  "candidates":33,
  "persisted":true,
  "generated_at":"2026-10-27 10:51:41.784234+00:00"
}
```

이후 백엔드·Vercel 경유 `GET /api/data/summary?month=11` 모두 200을 반환했고, `selected_record_count=14131`, `candidate_count=33`, `generated_at=2026-10-27T10:51:41.784234Z`가 일치했습니다.

## 목록 조회와 인덱스

최신 연월순 정렬에 필요한 복합 인덱스가 누락되어 목록 조회만 503이 발생했습니다. `firestore.indexes.json`에 정의된 전체 목록용·품목 검색용 인덱스 2개를 Firebase 콘솔에서 생성하고 사용 설정 후 재검증했습니다.

```text
GET /api/data?limit=1
HTTP 200; items=1; year_month=2024-12; has_more=true

GET /api/data?limit=1&item_name=감자
HTTP 200; items=1; item_name=감자; year_month=2024-12
```

다음은 인덱스 활성화 후 Vercel 데이터 관리 화면에서 실제 목록 30건이 로딩된 캡처입니다. 이 캡처는 목록 읽기의 증빙이며 앞선 임시 기록 생성·삭제 화면이라고 주장하지 않습니다.

![실제 최신순 가격 목록](../docs/images/desktop-manage.png)

## 모바일 화면 검증

검증 대상은 실제 Vercel 사이트입니다. Chrome의 뷰포트를 390×844 CSS 픽셀로 설정했습니다. 실물 휴대전화·소프트키보드·터치 동작까지 검증한 것은 아닙니다.

| 수행 행동 | 관찰 결과 |
| --- | --- |
| 재료 탐색 열기 | 14,131건·후보 33개·월 선택·순위 표시 |
| 문서 폭과 뷰포트 폭 비교 | 가로 넘침 없음 |
| `요리 챗봇` 클릭 | 고정 채팅 패널 표시 |
| 질문 입력란에 문장 입력 | 입력값 유지 확인 |
| 채팅 패널 영역 확인 | 390×844 뷰포트 내부에 표시 |
| 닫기 버튼 클릭 | 채팅 패널 숨김 확인 |
| AI 메시지 전송 | 수행하지 않음: 비용 절감, 이번 검증 범위는 UI 동작 |

실제 자동화 검사 결과:

```json
{
  "no_horizontal_overflow":true,
  "chat_open_and_input":true,
  "chat_inside_viewport":true,
  "chat_close":true,
  "ai_message_sent":false
}
```

<img src="../docs/images/mobile-explore.png" alt="390px 재료 탐색" width="320"> <img src="../docs/images/mobile-chat.png" alt="390px 채팅 입력 패널" width="320">

## 검증 범위

오프라인 Python 테스트 39개 통과는 별도 결과입니다. 위의 클라우드 HTTP·화면 증빙과 구분합니다. 대화 저장·불러오기는 사용자가 동작을 확인했으며, 이번 캡처 작업에서 실제 AI 답변 생성과 대화 저장을 다시 실행하지 않았습니다. 초기 안내 메시지를 AI 응답 증빙으로 사용하지 않습니다.
