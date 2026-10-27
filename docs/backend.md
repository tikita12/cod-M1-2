# FastAPI와 Firestore

## 실행

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
```

`.env`에 Firebase 프로젝트 ID, 서비스 계정 JSON의 로컬 경로, 관리자 키를 입력합니다.
AI 요리 챗봇을 사용하려면 `OPENAI_API_KEY`도 설정합니다.
기본 모델은 `gpt-5-mini`이며 `OPENAI_MODEL`로 바꿀 수 있습니다.
OpenAI API를 호출하면 계정 사용량에 따라 요금이 발생할 수 있습니다.
JSON 경로에 공백이 있으면 전체 경로를 큰따옴표로 감싸고 `/`를 사용하면 편합니다.
서비스 계정 JSON 본문은 대화나 프론트엔드 코드에 넣지 않습니다.

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

- 문서: http://127.0.0.1:8000/docs
- OpenAPI: http://127.0.0.1:8000/openapi.json
- 서버 상태: `/health`
- 실제 Firestore 연결 상태: `/health/ready`

Firebase 미설정 상태에서도 문서와 서버 상태는 열립니다.
DB에 접근하는 요청은 연결이 없으면 503을 반환합니다. 로컬 파일이나 임시 메모리에 저장하는 대체 동작은 없습니다.
Swagger UI의 Authorize에 `.env`의 `ADMIN_API_KEY`를 넣으면 추가·수정·삭제를 실행할 수 있습니다.
이는 관리자용 데이터 관리 인증입니다. 공개 프론트엔드 번들에 이 키를 넣어서는 안 됩니다.

## Firebase 최초 설정

1. Firebase Console에서 프로젝트를 만들거나 기존 프로젝트를 선택합니다.
2. Firestore Database에서 기본 데이터베이스를 생성합니다.
3. 프로젝트 설정 → 서비스 계정 → 새 비공개 키 생성으로 JSON 파일을 로컬에 저장합니다.
4. `.env`의 `FIREBASE_PROJECT_ID`, `GOOGLE_APPLICATION_CREDENTIALS`, `ADMIN_API_KEY`를 설정합니다.
5. 서버를 재시작한 뒤 `/health/ready`가 200인지 확인합니다.

서버 실행 전 읽기 전용 연결 점검도 가능합니다.

```powershell
.\.venv\Scripts\python.exe scripts/check_firestore.py
```

`Firestore connection OK`가 나오면 접속이 확인된 것입니다. 이 명령은 데이터를 저장하지 않습니다.
현재 에이전트 실행 환경에서는 외부 접속이 Windows 10013 오류로 차단되어 일반 터미널에서 확인이 필요합니다.

서버 SDK는 IAM/서비스 계정 권한으로 접근합니다. 제공한 `firestore.rules`는 브라우저의 직접 접근을 막는 규칙이며,
서버 API의 인증을 대신하지 않습니다. 현재 이 규칙 파일은 배포하지 않았습니다.
배포 환경에서는 서비스 계정 파일을 Secret File로 넣고 해당 서버 경로를 환경 변수에 지정합니다.

공식 참고: [Firestore 시작하기](https://firebase.google.com/docs/firestore/quickstart),
[에뮬레이터 연결](https://firebase.google.com/docs/emulator-suite/connect_firestore),
[FastAPI CORS](https://fastapi.tiangolo.com/tutorial/cors/).

## API

| 메서드 | 경로 | 기능 |
|---|---|---|
| GET | `/api/data/catalog` | 농산물 분류 목록 |
| GET | `/api/data` | 가격 자료 `year_month` 내림차순 목록, `limit`·`cursor`·`item_name` 지원 |
| POST | `/api/data` | 월별 가격 추가 |
| GET | `/api/data/{id}` | 한 건 조회 |
| PATCH | `/api/data/{id}` | 가격·메모 수정 |
| DELETE | `/api/data/{id}` | 삭제 |

목록은 등록일(`created_at`)이 아닌 가격 자료의 연월(`year_month`) 내림차순입니다.
같은 연월에서는 문서 ID 내림차순으로 순서를 고정합니다. Firestore에서 검색 조건에
맞는 전체 결과를 정렬한 뒤 `limit + 1`건만 읽어 페이지와 다음 페이지 유무를 결정합니다.
`item_name`은 기존처럼 품목명 정확히 일치 검색입니다.

다음 요청에는 응답의 `next_cursor`를 그대로 전달하고 같은 검색 조건을 유지합니다.
커서는 `YYYY-MM:문서ID` 형식으로 두 정렬 기준을 모두 포함하므로 같은 연월이 여러
페이지에 걸쳐 있어도 이어서 조회할 수 있습니다. 커서의 문서가 삭제되어도 추가 조회 없이
그 위치 다음부터 읽습니다. 검색 조건을 바꾸면 커서를 초기화합니다. 이전 ID 전용 커서는
지원하지 않으므로 배포 후 열려 있던 관리 화면은 새로고침해야 합니다.

품목 검색과 최신순 정렬에는 `firestore.indexes.json`에 정의한 복합 인덱스가 필요합니다.
Firebase 콘솔의 Firestore 인덱스에서 컬렉션 `data`, 범위 `Collection`, 필드
`item_name` 오름차순·`year_month` 내림차순·`__name__` 내림차순으로 생성하고
인덱스가 준비된 후 배포 환경의 검색을 확인합니다. 일반 목록은 `year_month` 내림차순
단일 필드 인덱스를 사용합니다. 코드 배포만으로 복합 인덱스가 생성되지는 않습니다.
| GET | `/api/data/summary?month=11` | 월별 하락 경향 요약 |
| GET | `/api/chat/status` | AI API 키 설정 여부 |
| POST | `/api/chat` | 분석 요약을 반영한 답변과 대화 저장 |
| GET | `/api/conversations?owner_id=...` | 저장된 대화 목록 |
| GET | `/api/conversations/{id}?owner_id=...` | 저장된 대화 불러오기 |

가격 추가 예시:

```json
{
  "year_month": "2024-11",
  "item_name": "배추",
  "variety_name": "가을",
  "grade_name": "상품",
  "quantity": 1,
  "unit": "포기",
  "average_price": 3500,
  "note": "가격 등록"
}
```

가격 수정은 `{"average_price": 3400, "note": "정정"}` 형식입니다.
연월·품목·품종·등급·판매 수량·단위는 기록의 식별 기준이어서 수정하지 않습니다.
이 조건을 잘못 입력했다면 올바른 기록을 추가하고 잘못된 기록을 삭제합니다.

## 구조와 컬렉션 설계

- `routers/data.py`: 경로, 상태 코드, HTTP 입력/응답 연결
- `schemas.py`: Pydantic 입력·응답 계약과 검증
- `services/prices.py`: 문서 생성, 분석 입력 구성, 요약
- `services/chat.py`: 월별 컨텍스트 구성, OpenAI Responses API 호출, 대화 저장 흐름
- `services/seasonality.py`: CSV와 API가 공통으로 사용하는 순수 분석 함수
- `repositories/firestore.py`: Firestore 저장·조회, 저장소 오류 변환
- `config.py`: 서버 환경 변수

`data/{id}` 한 문서는 월별 가격 한 건입니다.
ID는 연월·품목·품종·등급·환산 판매 수량·단위의 SHA-256입니다.
같은 기록을 동시에 추가해도 Firestore의 원자적 create가 중복을 막으며 가격 수정 시 ID는 유지됩니다.
100g와 0.1kg은 같은 조건으로 인식합니다. 100g와 1kg은 다른 조건입니다.

문서에는 입력 필드 외에 category, comparison_quantity, comparison_unit, source,
created_at, updated_at을 저장합니다. 가격과 수량은 소수 정밀도를 보존하는 문자열로 저장하고 계산 때 Decimal로 읽습니다.
목록은 문서 ID 순서의 커서 페이징입니다. 날짜 정렬은 아직 지원하지 않습니다.

`conversations/{uuid}` 문서에는 owner_id, title, created_at, updated_at, messages를 저장합니다.
메시지는 role, content, created_at을 가집니다. 챗봇 응답이 성공한 뒤 질문과 답변을 Firestore에 씁니다.
문서 하나에는 최근 100개 메시지를 보관합니다. 브라우저는 localStorage에 만든 무작위 owner_id로 자신의 대화를 조회합니다.
사용자 질문과 과거 대화는 AI 답변을 위해 OpenAI Responses API로 전송됩니다.
과거 가격 요약을 서버 지침에 주입하고 질문을 별도의 user 메시지로 전달합니다.
가격 숫자는 요약에 있는 값만 말하고, 과거 하락 경향을 미래 예측이라고 표현하지 않도록 안내합니다.

로그인 없이 익명 owner_id를 사용하는 과제용 구조입니다. 실제 공개 배포에는 Firebase 로그인 검증과 챗봇 API 사용량 제한이 필요합니다.

## 검증과 요약 갱신

완료된 월, 양수 가격·수량, 알려진 농산물·등급·단위, 문자열 길이를 검사합니다.
알 수 없는 필드, HTML 태그 기호, 제어 문자도 거부합니다.
메모는 요약이나 순위 계산에 사용하지 않습니다. 나중에 화면에 출력할 때도 textContent 등으로 렌더링해야 합니다.

요약은 서버 프로세스에서 한 번 계산하고 메모리에 저장합니다. 월 선택은 캐시된 12개월 결과를 사용합니다.
가격 추가·수정·삭제 API가 성공하면 캐시를 비워 다음 요약 요청에 변경 자료를 반영합니다.
앱 프로세스를 여러 개로 늘리면 각 프로세스가 한 번씩 Firestore를 읽고 별도 캐시를 갖습니다.
분석 범위 기본값은 2015~2024년이며 2015년 1월 비교용 2014년 12월도 조회합니다.
분석 기간은 환경 변수, 월별 계산 방식은 seasonality 서비스에서 변경합니다.
미래 가격 예측이나 최신 실시간 가격으로 표시하면 안 됩니다.

기본 조회 상한은 50,000건이며 넘으면 일부 데이터로 순위를 만들지 않고 오류를 반환합니다.
캐시가 처음 필요해지거나 데이터 관리 후 갱신할 때는 분석 기간의 전체 자료를 한 번 다시 읽습니다.
Firestore 콘솔 등 API 밖에서 직접 수정한 자료는 서버 재시작 후 캐시를 다시 만들기 전에는 요약에 반영되지 않습니다.

## 초기 CSV 적재

먼저 쓰기 없는 검증을 실행합니다.

```powershell
.\.venv\Scripts\python.exe scripts/import_firestore.py
```

연결 설정 후 아래처럼 적재할 수 있습니다. 기존 ID는 건너뛰어 수동 수정 내용을 덮어쓰지 않습니다.
전체 적재 전 `--limit 100`으로 적재 범위를 줄일 수 있습니다.

```powershell
.\.venv\Scripts\python.exe scripts/import_firestore.py --limit 100 --write
```

이 스크립트는 초기 CSV를 채우는 관리자 도구입니다. 앱을 켤 때 자동 적재하지 않습니다.

## 검증 범위

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

API 테스트는 명시적인 테스트 저장소를 사용합니다.
입력 검증, 권한, 중복, CRUD, 커서, 요약 갱신, CORS, 문서를 확인합니다.
Firestore 어댑터는 SDK 오류 매핑을 mock으로 확인합니다.
실제 Firestore CRUD와 배포 검증은 Firebase 프로젝트 인증 설정 후 별도로 수행해야 합니다.
챗봇의 요약 주입, 이전 대화 전달, 정상 답변 저장, 실패·불완전 답변 저장 방지와 월 변경 시 분석 캐시 재사용도 모의 테스트합니다. 실제 OpenAI 응답과 클라우드 대화 저장은 별도 확인이 필요합니다.

## 요리 챗봇 설정

프로젝트 루트의 `.env`에 `OPENAI_API_KEY`를 설정하고 서버를 재시작합니다.
`OPENAI_MODEL=gpt-5-mini`가 기본 모델입니다. 키는 프론트엔드나 채팅창에 넣지 않습니다.
웹의 **요리 챗봇** 메뉴에서 질문하고, **저장된 대화** 버튼으로 이전 대화를 불러옵니다.
질문과 정상 AI 답변 한 쌍을 Firestore에 저장하며, 저장 실패는 성공으로 표시하지 않습니다.
미리보기 모드에서는 AI 전송 및 대화 조회를 하지 않습니다.

OpenAI API 요청은 별도 사용 요금이 발생합니다. 출력 한도에는 추론 토큰도 포함되므로
불완전 응답은 정상 답변으로 저장하지 않습니다.
근거: [OpenAI 공식 문서](https://developers.openai.com/api/docs/guides/reasoning).

분석 결과는 `analysis_cache`의 압축된 `summary`와 `trends` 문서에 보관합니다.
서버가 새로 시작할 때는 revision 1회와 결과 문서 2회를 읽고, 결과는 프로세스 캐시에도 둡니다.
캐시가 없거나 revision·분석 기간이 다르면 원본 가격을 읽어 한 번 다시 계산합니다.
가격 API의 추가·수정·삭제는 revision을 바꾸며, CSV import는 작업당 한 번 바꿉니다.
Firestore 콘솔에서 직접 가격을 바꾼 경우 revision도 자동 변경해야 합니다.

이미 Firestore 가격 자료가 로컬 기준 CSV와 동일함을 확인했으며 캐시가 비어 있을 때는
다음 명령으로 revision 한 건을 조회하고 캐시 문서 2개를 미리 저장할 수 있습니다. 원본 가격 컬렉션 전체 스캔은 하지 않습니다.

```powershell
.\.venv\Scripts\python.exe scripts/seed_analysis_cache.py --write
```

CSV를 새로 적재할 때는 다음처럼 작업 끝에 캐시를 갱신합니다.

```powershell
.\.venv\Scripts\python.exe scripts/import_firestore.py --write --refresh-analysis-cache
```

가격 수정 직후 첫 분석은 cache miss라 전체 재계산이 필요합니다. 그 다음 서버 재시작부터는 캐시를 사용합니다.
할당량 복구 전에는 Firestore 캐시 쓰기·읽기도 제한될 수 있고 이미 초과한 사용량은 복구되지 않습니다.
