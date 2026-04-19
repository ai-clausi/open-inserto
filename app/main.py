from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import get_settings
from app.db.init_db import initialize_database
from app.web.routes import router as web_router


class Utf8JSONResponse(JSONResponse):
    media_type = "application/json; charset=utf-8"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    initialize_database(settings.database_path)
    yield


def _configure_logging(debug_enabled: bool) -> None:
    root_logger = logging.getLogger()
    level = logging.DEBUG if debug_enabled else logging.INFO
    if not root_logger.handlers:
        logging.basicConfig(
            level=level,
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
        )
        return
    root_logger.setLevel(level)


def create_app() -> FastAPI:
    settings = get_settings()
    _configure_logging(settings.app_debug)
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
        default_response_class=Utf8JSONResponse,
    )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> Utf8JSONResponse:
        return Utf8JSONResponse(status_code=exc.status_code, content={"detail": exc.detail}, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError) -> Utf8JSONResponse:
        return Utf8JSONResponse(status_code=422, content=jsonable_encoder({"detail": exc.errors()}))

    app.include_router(web_router)
    app.mount("/static", StaticFiles(directory="app/static"), name="static")
    app.mount("/data", StaticFiles(directory=settings.data_dir), name="data")
    return app


app = create_app()
