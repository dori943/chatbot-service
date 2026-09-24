from contextlib import asynccontextmanager

from fastapi             import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating  import Jinja2Templates
from fastapi.exceptions  import RequestValidationError
from sqlalchemy.exc      import SQLAlchemyError

from app.routers.auth    import router as login_router
from app.routers.chat    import router as chat_router
from app.core.errors     import (
    APIError, api_error_handler, validation_error_handler,
    database_error_handler, unexpected_error_handler,
)
from app.db              import engine
from app.core.logging    import configure_logging, RequestLoggingMiddleware

import uvicorn

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        yield
    finally:
        await engine.dispose()


configure_logging()

app = FastAPI(lifespan=lifespan)
app.add_middleware(RequestLoggingMiddleware)
app.add_exception_handler(APIError, api_error_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)
app.add_exception_handler(SQLAlchemyError, database_error_handler)
app.add_exception_handler(Exception, unexpected_error_handler)
app.include_router(login_router)
app.include_router(chat_router)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

@app.get("/")
def home(request: Request):
    return templates.TemplateResponse(
        request,
        "index.html",
        {"request": request}
    )

if __name__ == "__main__":
    # 요청 로그는 RequestLoggingMiddleware에서 기록한다.
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, access_log=False)
