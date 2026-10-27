# 제철한끼 화면

`frontend/`는 설치나 빌드 없이 제공할 수 있는 HTML·CSS·JavaScript 웹페이지입니다.
FastAPI가 `/`에서 같은 파일을 제공하므로 로컬에서는 API 주소 설정 없이 동작합니다.

## 실행 중인 서버에 새 화면 반영

기존 서버 터미널에서 Ctrl+C를 누른 뒤 다시 실행합니다.

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8001 --reload
```

브라우저에서 http://127.0.0.1:8001/ 을 엽니다.
데이터는 `/api/data/summary`에서 읽습니다. 선택한 월의 결과는 브라우저 메모리에 5분간 보관합니다.
새로고침 버튼은 현재 서버 분석 결과를 다시 불러오고, 데이터 추가·수정·삭제는 서버 분석 캐시를 무효화합니다.
첫 접속 지연·오류·검색 결과 없음은 각각 화면에 안내합니다.

## 구현 기능

- 1~12월 선택, 품목 분류, 이름 검색, 하락 폭/빈도/이름순 정렬
- 아이콘을 넣은 줄 단위 순위와 근거 보기
- 분석 기간·표본 수·과거 데이터라는 점 표시
- 월별 가격 목록·품목 검색·더 불러오기
- 관리자 키를 입력한 뒤 가격 추가, 가격·메모 수정, 확인 후 삭제
- 데이터 변경 후 목록과 다음 분석 조회에 반영
- 작은 화면에서 메뉴·월 선택·카드·입력 폼 재배치
- 월별 요약을 참고하는 요리 챗봇, 새 대화, 대화 목록과 불러오기

관리자 키는 `.env`의 `ADMIN_API_KEY` 값입니다.
웹 화면의 관리자 인증 입력란에서 이 탭 동안만 사용하며 localStorage나 파일에 저장하지 않습니다.
키를 화면 소스 코드에 넣지 않습니다. 이 값은 서버 설정 파일에서 직접 확인할 수 있습니다.
화면에서 외부 데이터를 표시할 때는 textContent를 사용합니다.
챗봇을 켜려면 서버 `.env`의 `OPENAI_API_KEY`가 필요합니다.
질문과 대화 기록은 답변 생성을 위해 기관 AI API(`https://copa.codyssey.kr/v1/chat/completions`, 모델 `gpt-5-mini`)로 전달되고, 답변을 받으면 Firestore에 저장됩니다.
키가 없으면 챗봇 화면에 설정 필요 안내가 나타납니다.

## 저장된 분석 미리보기

`/?preview=1&month=11`은 공개 CSV로 미리 계산한 결과를 사용합니다.
화면에 미리보기임을 표시하며 이 모드에서는 가격을 변경하지 않습니다.
실제 서버 연결 실패 시 자동으로 샘플 결과로 대체하지 않고, 사용자가 미리보기를 선택하도록 합니다.
샘플은 `frontend/sample/seasonal_rankings.json`이고, 원본 분석을 갱신하면 이 파일도 갱신해야 합니다.

## Vercel 배포 완료

프론트엔드 주소: **https://cod-m1-2-frontend.vercel.app**

백엔드 주소: https://geogyfood.onrender.com

Vercel은 `frontend` 디렉터리의 정적 파일을 제공합니다.
`frontend/config.js`의 `apiBase`는 빈 값으로 유지하며, 브라우저는 같은 도메인의 `/api/...`로 요청합니다.
`frontend/vercel.json`의 rewrite가 `/api/:path*`를 `https://geogyfood.onrender.com/api/:path*`로 전달하므로 Render 주소를 `apiBase`에 직접 넣을 필요가 없습니다.
프론트에서 Render를 직접 호출하는 방식으로 바꿀 때는 Render의 `ALLOWED_ORIGINS` 설정도 확인해야 합니다.
Firebase 인증 파일과 `.env`는 Vercel 프론트엔드에 올리지 않습니다.

AI 응답을 생성하면 기관 API 사용량이 발생할 수 있습니다.
Vercel에 프론트엔드를 배포할 때 API 키를 `config.js`나 프론트엔드 환경 변수에 두지 않습니다.

## 검증

JavaScript 문법 검사, FastAPI 정적 파일 응답, API 회귀 테스트를 수행했습니다.
2026-10-27에는 Vercel 경유 재료 목록 64개, 프론트·백엔드 요약 200 응답(가격 기록 14,131건·11월 후보 33개), 배포된 JS·CSS와 로컬 파일 일치를 확인했습니다.
모바일 채팅 고정 패널은 로컬 화면에서 확인했으며, 실제 모바일 기기 전체 동작을 검증한 것은 아닙니다.
