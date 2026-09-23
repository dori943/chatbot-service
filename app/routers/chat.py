import logging

from fastapi               import APIRouter, Depends, Query
from fastapi.exceptions    import RequestValidationError
from fastapi.routing       import APIRoute
from sqlalchemy.orm        import Session

from app.core.dependencies import get_token_id
from app.core.errors       import APIError, api_error_handler
from app.schemas.chat      import ChatRequest
from app.services          import ai_service
from app.db                import get_db
from app.services          import chat_main

logger = logging.getLogger(__name__)

class ChatRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request):
            try: return await original(request)

            except RequestValidationError:
                return await api_error_handler(request, APIError(422, "INVALID_INPUT", "요청 내용을 확인해 주세요. 질문은 공백만으로 구성할 수 없으며 최대 5,000자입니다.",))
        return handler

router = APIRouter(prefix="/api", tags=["chat"])

@router.post("/chat")
async def send_chat(data: ChatRequest, user_id: str = Depends(get_token_id), db: Session = Depends(get_db)):
    return await chat_main.chat(data, user_id, db)

@router.get("/me/chats")
async def get_my_chat(user_id: str=Depends(get_token_id), db: Session = Depends(get_db)):
    return await chat_main.get_my_chat(user_id, db)
