from contextlib          import asynccontextmanager

import uvicorn

from fastapi             import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating  import Jinja2Templates
from fastapi.exceptions  import RequestValidationError
from sqlalchemy.exc      import SQLAlchemyError

from app.core.errors     import (
    APIError,
    api_error_handler,
    validation_error_handler,
    database_error_handler,
    unexpected_error_handler,
)
from app.core.logging    import configure_logging, RequestLoggingMiddleware
from app.db              import engine
from app.routers.auth    import router as login_router
from app.routers.chat    import router as chat_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        yield
    finally:
        await engine.dispose()


configure_logging()

# 1. FastAPI 인스턴스 생성 및 수명 주기(lifespan) 관리
app = FastAPI(lifespan=lifespan)
# 2. 전역 미들웨어 등록: 모든 HTTP 요청/응답에 대한 로깅 처리
app.add_middleware(RequestLoggingMiddleware)
# 3. 전역 예외 처리기(Exception Handler) 등록: 예외 유형별 통합 응답 처리
app.add_exception_handler(APIError, api_error_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)
app.add_exception_handler(SQLAlchemyError, database_error_handler)
app.add_exception_handler(Exception, unexpected_error_handler)
# 4. 모듈화된 라우터(Router) 등록: Auth, Chat 도메인 API 연동
app.include_router(login_router)
app.include_router(chat_router)

# 5. 정적 파일 및 템플릿 엔진 설정
# - StaticFiles: CSS, JS 등 프론트엔드 정적 리소스 서빙 경로 설정
app.mount("/static", StaticFiles(directory="static"), name="static")
# - Jinja2Templates: Server-Side Rendering(SSR)을 위한 템플릿 엔진 초기화
templates = Jinja2Templates(directory="templates")


# 6. 루트 엔드포인트: 기본 접속 시 index.html 화면 렌더링 및 서빙
@app.get("/")
def home(request: Request):
    return templates.TemplateResponse(
        request,
        "index.html",
    )

if __name__ == "__main__":
    # 요청 로그는 RequestLoggingMiddleware에서 기록한다.
    # 7. Uvicorn WAS(Web Application Server) 실행 설정
    uvicorn.run(app, host="0.0.0.0", port=8000, access_log=False)
