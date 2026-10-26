import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security import APIKeyHeader

from app.repositories.firestore import FirestoreRepository
from app.services.prices import PriceService

admin_header = APIKeyHeader(name="X-Admin-Key", auto_error=False, description="데이터 관리용 서버 관리자 키")


def require_admin(request: Request, key: Annotated[str | None, Depends(admin_header)]):
    expected = request.app.state.settings.admin_api_key
    if not expected:
        raise HTTPException(503, "관리자 키가 설정되지 않았습니다")
    if key is None or not secrets.compare_digest(key.encode(), expected.encode()):
        raise HTTPException(401, "관리자 인증이 필요합니다")


def repository(request: Request):
    with request.app.state.repository_lock:
        if request.app.state.repository is None:
            request.app.state.repository = FirestoreRepository(request.app.state.settings)
    return request.app.state.repository


def price_service(request: Request, store=Depends(repository)):
    with request.app.state.price_service_lock:
        if request.app.state.price_service is None:
            request.app.state.price_service = PriceService(store, request.app.state.settings)
        return request.app.state.price_service


def chat_service(request: Request, store=Depends(repository), prices=Depends(price_service)):
    from app.services.chat import ChatService
    return ChatService(store, prices, request.app.state.settings)
