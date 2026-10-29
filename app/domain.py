from dataclasses import dataclass
from enum import StrEnum


class Product(StrEnum):
    PHONE = "PHONE"
    TWIST = "TWIST"
    CARD = "CARD"


class Status(StrEnum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ReasonCode(StrEnum):
    SCORE_BELOW_MINIMUM = "SCORE_BELOW_MINIMUM"
    EMPLOYMENT_BELOW_MINIMUM = "EMPLOYMENT_BELOW_MINIMUM"
    INSTALLMENT_ABOVE_LIMIT = "INSTALLMENT_ABOVE_LIMIT"
    INCOME_BELOW_MINIMUM = "INCOME_BELOW_MINIMUM"
    AMOUNT_ABOVE_LIMIT = "AMOUNT_ABOVE_LIMIT"


@dataclass(frozen=True)
class Reason:
    code: ReasonCode
    message: str
