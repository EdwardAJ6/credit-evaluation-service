from collections.abc import Mapping
from dataclasses import dataclass
from typing import ClassVar

from app.domain import Product, Reason, ReasonCode


@dataclass(frozen=True, kw_only=True)
class ConservativePolicy:
    name: ClassVar[str] = "CONSERVATIVE"
    min_score: int = 700
    min_employment_months: int = 12
    max_installment_pct: int = 25
    term_months: int = 12

    def evaluate(self, applicant) -> list[Reason]:
        reasons = []
        if applicant.external_score < self.min_score:
            reasons.append(_score_reason(applicant.external_score, self.min_score))
        if applicant.employment_months < self.min_employment_months:
            reasons.append(
                Reason(
                    ReasonCode.EMPLOYMENT_BELOW_MINIMUM,
                    f"employment_months {applicant.employment_months} "
                    f"is below the minimum {self.min_employment_months}",
                )
            )
        reasons += _installment_reasons(
            applicant, self.max_installment_pct, self.term_months
        )
        return reasons


@dataclass(frozen=True, kw_only=True)
class StandardPolicy:
    name: ClassVar[str] = "STANDARD"
    min_score: int = 600
    max_installment_pct: int = 35
    term_months: int = 12

    def evaluate(self, applicant) -> list[Reason]:
        reasons = []
        if applicant.external_score < self.min_score:
            reasons.append(_score_reason(applicant.external_score, self.min_score))
        reasons += _installment_reasons(
            applicant, self.max_installment_pct, self.term_months
        )
        return reasons


@dataclass(frozen=True, kw_only=True)
class AggressivePolicy:
    name: ClassVar[str] = "AGGRESSIVE"
    min_score: int = 550
    reduced_min_score: int = 500
    min_monthly_income: int = 3_000_000
    # The statement's literal rule ignores affordability and approved, e.g.,
    # score 550, income 0 and amount 100,000,000. Product decision: the
    # installment is capped at 50% of income (the usual debt ceiling) and the
    # amount at 20,000,000.
    max_installment_pct: int = 50
    term_months: int = 12
    max_amount: int = 20_000_000

    def evaluate(self, applicant) -> list[Reason]:
        score, income = applicant.external_score, applicant.monthly_income
        meets_income = income >= self.min_monthly_income
        reasons = []
        if not (
            score >= self.min_score
            or (score >= self.reduced_min_score and meets_income)
        ):
            # Cite the score minimum that applies with the current income.
            minimum = self.reduced_min_score if meets_income else self.min_score
            reasons.append(_score_reason(score, minimum))
            if not meets_income:
                reasons.append(
                    Reason(
                        ReasonCode.INCOME_BELOW_MINIMUM,
                        f"monthly_income {income} is below the minimum "
                        f"{self.min_monthly_income} required to qualify with "
                        f"external_score from {self.reduced_min_score} "
                        f"to {self.min_score - 1}",
                    )
                )
        reasons += _installment_reasons(
            applicant, self.max_installment_pct, self.term_months
        )
        if applicant.amount > self.max_amount:
            reasons.append(
                Reason(
                    ReasonCode.AMOUNT_ABOVE_LIMIT,
                    f"amount {applicant.amount} exceeds the maximum {self.max_amount}",
                )
            )
        return reasons


Policy = ConservativePolicy | StandardPolicy | AggressivePolicy


def get_policies() -> Mapping[Product, Policy]:
    return {
        Product.PHONE: ConservativePolicy(),
        Product.TWIST: StandardPolicy(),
        Product.CARD: AggressivePolicy(),
    }


def _score_reason(score: int, minimum: int) -> Reason:
    return Reason(
        ReasonCode.SCORE_BELOW_MINIMUM,
        f"external_score {score} is below the minimum {minimum}",
    )


def _installment_reasons(
    applicant, max_installment_pct: int, term_months: int
) -> list[Reason]:
    # amount / term_months <= pct% of income, multiplied out: exact in integers
    # and safe with an income of 0.
    if (
        100 * applicant.amount
        <= max_installment_pct * term_months * applicant.monthly_income
    ):
        return []
    return [
        Reason(
            ReasonCode.INSTALLMENT_ABOVE_LIMIT,
            f"amount {applicant.amount} over {term_months} months exceeds "
            f"{max_installment_pct}% of monthly_income {applicant.monthly_income}",
        )
    ]
