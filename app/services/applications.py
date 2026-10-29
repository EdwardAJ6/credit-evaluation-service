from collections.abc import Mapping
from dataclasses import asdict
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.domain import Product, Status
from app.models import Application, Evaluation
from app.repositories.applications import ApplicationRepository
from app.strategies.policies import Policy


class ApplicationService:
    """Use cases. Each write commits exactly once, so an application and its
    evaluations never disagree. Reads never commit."""

    def __init__(self, db: Session, policies: Mapping[Product, Policy]) -> None:
        self._db = db
        self._policies = policies
        self._repository = ApplicationRepository(db)

    def create(self, data: dict) -> Application:
        now = datetime.now(UTC)
        # Not added explicitly: adding its evaluation cascades to it.
        application = Application(**data, created_at=now)
        self._evaluate(application, now)
        self._db.commit()
        return application

    def get(self, application_id: int) -> Application | None:
        return self._repository.get(application_id)

    def search(self, **params) -> list[Application]:
        return self._repository.search(**params)

    def reevaluate(self, application_id: int) -> Application | None:
        application = self._repository.get(application_id)
        if application is None:
            return None
        self._evaluate(application, datetime.now(UTC))
        self._db.commit()
        return application

    def _evaluate(self, application: Application, now: datetime) -> None:
        policy = self._policies[Product(application.product)]
        reasons = [asdict(reason) for reason in policy.evaluate(application)]
        evaluation = Evaluation(
            application=application,
            status=Status.REJECTED if reasons else Status.APPROVED,
            rejection_reasons=reasons,
            policy={"name": policy.name, **asdict(policy)},
            evaluated_at=now,
        )
        self._db.add(evaluation)
        # The current decision is assigned (never mutated) from that evaluation.
        application.status = evaluation.status
        application.rejection_reasons = evaluation.rejection_reasons
        application.evaluated_at = evaluation.evaluated_at
