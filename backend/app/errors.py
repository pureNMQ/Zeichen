"""统一错误四件套(规格书 §4.1):permission_denied / not_found / conflict / invalid_request。

HTTP 与 MCP 共用同一错误类型;HTTP 侧由 FastAPI handler 转 JSON
{code, message},MCP 侧由工具包装层转 MCP 错误。
"""

from fastapi import Request
from fastapi.responses import JSONResponse

CODE_STATUS = {
    "unauthorized": 401,
    "permission_denied": 403,
    "not_found": 404,
    "conflict": 409,
    "invalid_request": 400,
}


class AppError(Exception):
    """业务错误:code ∈ 四件套(+ unauthorized),status_code 由 code 映射。"""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        self.status_code = CODE_STATUS.get(code, 400)
        super().__init__(message)


def unauthorized(message: str) -> AppError:
    return AppError("unauthorized", message)


def permission_denied(message: str) -> AppError:
    return AppError("permission_denied", message)


def not_found(message: str) -> AppError:
    return AppError("not_found", message)


def conflict(message: str) -> AppError:
    return AppError("conflict", message)


def invalid_request(message: str) -> AppError:
    return AppError("invalid_request", message)


def install_error_handler(app) -> None:
    @app.exception_handler(AppError)
    async def _app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": exc.code, "message": exc.message},
        )
