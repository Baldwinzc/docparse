from __future__ import annotations

from uuid import uuid4

from fastapi import FastAPI, Request

from docparse.api.errors import unhandled_error_handler
from docparse.api.routes import REQUEST_ID_HEADER, router
from docparse.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="xlsx → 一张报关单 JSON。解析走 pipeline，本层只收文件和调用方参数。",
    )

    @app.middleware("http")
    async def request_id_mw(request: Request, call_next):
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid4().hex
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response

    app.add_exception_handler(Exception, unhandled_error_handler)
    app.include_router(router)
    return app


app = create_app()
