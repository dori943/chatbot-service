from fastapi           import Request
from fastapi.responses import JSONResponse

from app.schemas.chat  import ErrorResponse


class APIError(Exception):
    def __init__(self, status_code: int, error_code: str, message: str,
                       request_id : str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.body        = ErrorResponse(error_code=error_code, message=message, request_id=request_id)

async def api_error_handler(request: Request, exc: APIError):
    headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
    return JSONResponse(status_code=exc.status_code, content=exc.body.model_dump(), headers=headers)
