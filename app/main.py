from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating  import Jinja2Templates

from app.routers.auth import router as login_router
from app.routers.chat import router as chat_router
from app.core.errors  import APIError, api_error_handler
from app.db           import engine

import uvicorn

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        yield
    finally:
        await engine.dispose()


app = FastAPI(lifespan=lifespan)
app.add_exception_handler(APIError, api_error_handler)
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
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000)
