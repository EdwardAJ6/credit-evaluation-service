import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

# Imported for its side effect: registers the tables in Base.metadata.
from app import models  # noqa: F401
from app.api import router
from app.database import Base, engine
from app.schemas import HealthResponse


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if not os.environ.get("API_KEY"):  # fail closed: never serve without a key
        raise RuntimeError("API_KEY is not set")
    Base.metadata.create_all(bind=engine)  # on startup, never on import
    yield


# The trailing-slash redirect would build its URL from the client's Host header.
app = FastAPI(
    title="Credit Evaluation Service", lifespan=lifespan, redirect_slashes=False
)
app.include_router(router)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    # FastAPI's default 422 body minus "input": it would echo income and score,
    # and a NaN in it turns the response into a 500.
    errors = [
        {key: value for key, value in error.items() if key != "input"}
        for error in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": jsonable_encoder(errors)})


@app.get("/health", response_model=HealthResponse)
def health():
    return {"status": "ok"}
