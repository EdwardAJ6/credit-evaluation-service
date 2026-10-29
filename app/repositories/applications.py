from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain import Product, Status
from app.models import Application


class ApplicationRepository:
    """The only place that builds queries. It never commits: the service does."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def get(self, application_id: int) -> Application | None:
        return self._db.get(Application, application_id)

    def search(
        self,
        *,
        status: Status | None,
        product: Product | None,
        limit: int,
        offset: int,
    ) -> list[Application]:
        query = select(Application)
        if status is not None:
            query = query.where(Application.status == status)
        if product is not None:
            query = query.where(Application.product == product)
        query = query.order_by(Application.id.desc()).limit(limit).offset(offset)
        return list(self._db.scalars(query))
