import logging
from threading import Lock

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from app.config import ROOT, Settings
from app.dependencies import repository
from app.errors import (AIUnavailable, ConversationNotFound, RecordConflict,
                        RecordNotFound, StoreUnavailable, StoreQuotaExceeded, StoreTimeout, TooManyRecords)
from app.routers.chat import router as chat_router
from app.routers.data import router


def create_app(settings=None, store=None):
    settings = settings or Settings.from_env()
    if not 1996 <= settings.analysis_start_year <= settings.analysis_end_year or settings.analysis_min_years < 1:
        raise ValueError("분석 환경 변수의 기간/최소 연도 수를 확인하세요")
    app = FastAPI(title="농산물 가격 분석 API", version="0.1.0",
                  description="월별 가격 CRUD와 과거 계절적 하락 경향 분석. 실제 미래 가격 예측값은 아닙니다.")
    app.state.settings = settings
    app.state.repository = store
    app.state.repository_lock = Lock()
    app.state.price_service = None
    app.state.price_service_lock = Lock()
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.allowed_origins),
                       allow_credentials=False, allow_methods=["GET", "POST", "PATCH", "DELETE"],
                       allow_headers=["Content-Type", "X-Admin-Key"])

    @app.exception_handler(StoreUnavailable)
    async def unavailable(request, exc):
        return JSONResponse(status_code=503, content={"detail": "Firestore 연결을 확인하세요. Firebase 프로젝트·인증·네트워크 설정이 필요합니다."})

    @app.exception_handler(StoreQuotaExceeded)
    async def quota_exceeded(request, exc):
        return JSONResponse(status_code=503, content={
            "code": "firestore_quota_exceeded",
            "detail": "Firestore 할당량 또는 요청 한도를 초과했습니다. Firebase 콘솔에서 사용량을 확인하세요. 가격 조회나 대화 저장이 제한되어 챗봇 요청을 완료하지 못했습니다. OpenAI 키를 바꿀 필요는 없습니다."})

    @app.exception_handler(StoreTimeout)
    async def timeout(request, exc):
        return JSONResponse(status_code=503, content={
            "code": "firestore_timeout",
            "detail": "Firestore 요청 시간이 초과되었습니다. 잠시 후 다시 시도하세요."})

    @app.exception_handler(RecordConflict)
    async def conflict(request, exc):
        return JSONResponse(status_code=409, content={"detail": "같은 연월·품목·품종·등급·수량·단위의 가격이 이미 있습니다."})

    @app.exception_handler(RecordNotFound)
    async def missing(request, exc):
        return JSONResponse(status_code=404, content={"detail": "가격 기록을 찾을 수 없습니다."})

    @app.exception_handler(TooManyRecords)
    async def capacity(request, exc):
        return JSONResponse(status_code=503, content={"detail": "분석 건수 한도를 초과했습니다. 분석 기간이나 요약 방식을 조정하세요."})

    @app.exception_handler(ConversationNotFound)
    async def conversation_missing(request, exc):
        return JSONResponse(status_code=404, content={"detail": "대화를 찾을 수 없습니다."})

    @app.exception_handler(AIUnavailable)
    async def ai_unavailable(request, exc):
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    @app.exception_handler(ValidationError)
    async def corrupt_data(request, exc):
        logging.getLogger(__name__).warning("Stored data validation failed")
        return JSONResponse(status_code=503, content={"detail": "저장된 데이터 형식 검증에 실패했습니다. 관리자 확인이 필요합니다."})

    @app.get("/health", tags=["상태"], summary="서버 실행 상태 (DB 연결 검증과 별도)")
    def health():
        return {"status": "ok", "storage": "firestore", "firestore_configured": bool(settings.firebase_project_id)}

    @app.get("/health/ready", tags=["상태"], summary="Firestore 실제 연결 확인")
    def ready(store=Depends(repository)):
        store.probe()
        return {"status": "ready", "storage": "firestore"}

    app.include_router(router)
    app.include_router(chat_router)
    app.mount("/", StaticFiles(directory=ROOT / "frontend", html=True), name="frontend")
    return app


app = create_app()
