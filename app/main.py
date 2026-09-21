from fastapi import FastAPI

from routers.auth import router as login_router

import uvicorn

app = FastAPI()
app.include_router(login_router)

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000)