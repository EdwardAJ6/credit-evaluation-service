import os
import secrets
from collections.abc import Mapping
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response
from fastapi.security import APIKeyHeader
from sqlalchemy.orm import Session

from app.database import get_db
from app.domain import Product
from app.schemas import MAX_INT, ApplicationCreate, ApplicationOut, ListParams
from app.services.applications import ApplicationService
from app.strategies.policies import Policy, get_policies

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_key(key: Annotated[str | None, Depends(api_key_header)]) -> None:
    expected = os.environ.get("API_KEY")
    # Bytes, not str: a non-ASCII header would make compare_digest raise (500).
    if not (
        expected and key and secrets.compare_digest(key.encode(), expected.encode())
    ):
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )


router = APIRouter(dependencies=[Depends(require_api_key)])

ApplicationId = Annotated[int, Path(ge=1, le=MAX_INT)]


def get_service(
    db: Annotated[Session, Depends(get_db)],
    policies: Annotated[Mapping[Product, Policy], Depends(get_policies)],
) -> ApplicationService:
    return ApplicationService(db, policies)


ServiceDep = Annotated[ApplicationService, Depends(get_service)]


@router.post("/applications", status_code=201, response_model=ApplicationOut)
def create_application(
    data: ApplicationCreate, response: Response, service: ServiceDep
):
    application = service.create(data.model_dump())
    # Relative on purpose: never rebuilt from the client's Host header.
    response.headers["Location"] = f"/applications/{application.id}"
    return application


@router.get("/applications", response_model=list[ApplicationOut])
def list_applications(params: Annotated[ListParams, Query()], service: ServiceDep):
    return service.search(**params.model_dump())


@router.get("/applications/{application_id}", response_model=ApplicationOut)
def get_application(application_id: ApplicationId, service: ServiceDep):
    return _or_404(service.get(application_id))


@router.post("/applications/{application_id}/reevaluate", response_model=ApplicationOut)
def reevaluate_application(application_id: ApplicationId, service: ServiceDep):
    return _or_404(service.reevaluate(application_id))


def _or_404(application):
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")
    return application
