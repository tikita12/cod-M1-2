from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request

from app.dependencies import chat_service
from app.schemas import ChatRequest, ChatResponse, ConversationDetail, ConversationList

router = APIRouter(prefix="/api", tags=["요리 챗봇"])
OwnerId = Annotated[str, Query(pattern=r"^[0-9a-f-]{36}$")]
ConversationId = Annotated[str, Path(pattern=r"^[0-9a-f-]{36}$")]


@router.get("/chat/status", summary="요리 챗봇 설정 상태")
def chat_status(request: Request):
    key_set = bool(request.app.state.settings.openai_api_key)
    return {"configured": key_set, "model": request.app.state.settings.openai_model if key_set else None}


@router.post("/chat", response_model=ChatResponse, summary="월별 요리 추천 챗봇")
def chat(payload: ChatRequest, service=Depends(chat_service)):
    return service.answer(payload)


@router.get("/conversations", response_model=ConversationList, summary="저장된 대화 목록")
def conversation_list(owner_id: OwnerId, service=Depends(chat_service)):
    return service.conversations(owner_id)


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail,
            summary="저장된 대화 불러오기")
def conversation_detail(conversation_id: ConversationId, owner_id: OwnerId,
                        service=Depends(chat_service)):
    return service.conversation(conversation_id, owner_id)
