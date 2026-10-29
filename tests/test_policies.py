from dataclasses import FrozenInstanceError, asdict, replace
from fractions import Fraction
from types import SimpleNamespace

import pytest

from app.domain import Product, ReasonCode
from app.strategies.policies import (
    AggressivePolicy,
    ConservativePolicy,
    StandardPolicy,
    get_policies,
)

SCORE = ReasonCode.SCORE_BELOW_MINIMUM
EMPLOYMENT = ReasonCode.EMPLOYMENT_BELOW_MINIMUM
INSTALLMENT = ReasonCode.INSTALLMENT_ABOVE_LIMIT
INCOME = ReasonCode.INCOME_BELOW_MINIMUM
AMOUNT = ReasonCode.AMOUNT_ABOVE_LIMIT

PHONE, TWIST, CARD = Product.PHONE, Product.TWIST, Product.CARD

# Spec section 9: product, amount, monthly_income, employment_months,
# external_score and the expected codes, in order.
ROWS = {
    "R01": (PHONE, 2_400_000, 1_500_000, 24, 750, []),
    "R02": (PHONE, 3_000_000, 1_000_000, 12, 700, []),
    "R03": (PHONE, 3_000_000, 1_000_000, 12, 699, [SCORE]),
    "R04": (PHONE, 3_000_000, 1_000_000, 11, 700, [EMPLOYMENT]),
    "R05": (PHONE, 3_000_001, 1_000_000, 12, 700, [INSTALLMENT]),
    "R06": (PHONE, 4_000_000, 1_000_000, 6, 650, [SCORE, EMPLOYMENT, INSTALLMENT]),
    "R07": (TWIST, 4_000_000, 1_000_000, 0, 650, []),
    "R08": (TWIST, 5_880_000, 1_400_000, 0, 600, []),
    "R09": (TWIST, 4_200_001, 1_000_000, 0, 600, [INSTALLMENT]),
    "R10": (TWIST, 4_200_000, 1_000_000, 0, 599, [SCORE]),
    "R11": (TWIST, 1, 0, 0, 700, [INSTALLMENT]),
    "R12": (TWIST, 5_000_000, 1_000_000, 0, 500, [SCORE, INSTALLMENT]),
    "R13": (CARD, 100_000_000, 0, 0, 550, [INSTALLMENT, AMOUNT]),
    "R14": (CARD, 1_000_000, 3_000_000, 0, 500, []),
    "R15": (CARD, 1_000_000, 3_000_000, 0, 499, [SCORE]),
    "R16": (CARD, 1_000_000, 2_999_999, 0, 549, [SCORE, INCOME]),
    "R17": (CARD, 1_000_000, 1_000_000, 0, 450, [SCORE, INCOME]),
    "R18": (TWIST, 2_162_374_928_317_145, 514_851_173_408_844, 0, 600, [INSTALLMENT]),
    "R19": (CARD, 6_000_000, 1_000_000, 0, 550, []),
    "R20": (CARD, 6_000_001, 1_000_000, 0, 550, [INSTALLMENT]),
    "R21": (CARD, 20_000_000, 4_000_000, 0, 550, []),
    "R22": (CARD, 20_000_001, 4_000_000, 0, 550, [AMOUNT]),
    "R23": (CARD, 30_000_000, 1_000_000, 0, 450, [SCORE, INCOME, INSTALLMENT, AMOUNT]),
}

# Spec section 6.2, written out so no expectation is read from the instances.
THRESHOLDS = {
    PHONE: {
        "min_score": 700,
        "min_employment_months": 12,
        "max_installment_pct": 25,
        "term_months": 12,
    },
    TWIST: {"min_score": 600, "max_installment_pct": 35, "term_months": 12},
    CARD: {
        "min_score": 550,
        "reduced_min_score": 500,
        "min_monthly_income": 3_000_000,
        "max_installment_pct": 50,
        "term_months": 12,
        "max_amount": 20_000_000,
    },
}


def applicant(row_id):
    _, amount, monthly_income, employment_months, external_score, _ = ROWS[row_id]
    return SimpleNamespace(
        amount=amount,
        monthly_income=monthly_income,
        employment_months=employment_months,
        external_score=external_score,
    )


@pytest.mark.parametrize("row_id", [row_id for row_id in ROWS if not ROWS[row_id][-1]])
def test_ac01_default_policy_returns_no_reasons_for_approved_rows(row_id):
    policy = get_policies()[ROWS[row_id][0]]
    assert policy.evaluate(applicant(row_id)) == []


@pytest.mark.parametrize("row_id", [row_id for row_id in ROWS if ROWS[row_id][-1]])
def test_ac02_default_policy_returns_the_row_codes_in_order(row_id):
    policy = get_policies()[ROWS[row_id][0]]
    reasons = policy.evaluate(applicant(row_id))
    assert [reason.code for reason in reasons] == ROWS[row_id][-1]


def test_ac03_registry_keys_are_exactly_the_products():
    assert set(get_policies()) == set(Product)


@pytest.mark.parametrize(
    ("product", "policy_class", "name"),
    [
        pytest.param(PHONE, ConservativePolicy, "CONSERVATIVE", id="PHONE"),
        pytest.param(TWIST, StandardPolicy, "STANDARD", id="TWIST"),
        pytest.param(CARD, AggressivePolicy, "AGGRESSIVE", id="CARD"),
    ],
)
def test_ac03_registry_holds_the_default_policy_of_each_product(
    product, policy_class, name
):
    policy = get_policies()[product]
    assert type(policy) is policy_class
    assert asdict(policy) == THRESHOLDS[product]
    assert all(type(value) is int for value in asdict(policy).values())
    assert type(policy).name == name


def test_ac04_replaced_min_score_rejects_r07():
    stricter = replace(StandardPolicy(), min_score=700)
    assert [reason.code for reason in stricter.evaluate(applicant("R07"))] == [SCORE]


@pytest.mark.parametrize("product", list(Product))
def test_ac04_policies_are_frozen(product):
    policy = get_policies()[product]
    with pytest.raises(FrozenInstanceError):
        policy.min_score = 0


@pytest.mark.parametrize("product", [PHONE, TWIST, CARD])
def test_ac05_installment_rule_matches_the_exact_fraction(product):
    thresholds = THRESHOLDS[product]
    pct = thresholds["max_installment_pct"]
    policy = get_policies()[product]
    for income in range(0, 20_000_001, 7_919):
        boundary = pct * 12 * income // 100
        # boundary - 1, boundary and boundary + 1, keeping only amounts >= 1
        for amount in range(max(boundary - 1, 1), boundary + 2):
            case = SimpleNamespace(
                amount=amount,
                monthly_income=income,
                employment_months=thresholds.get("min_employment_months", 0),
                external_score=thresholds["min_score"],
            )
            accepted = INSTALLMENT not in [r.code for r in policy.evaluate(case)]
            expected = Fraction(amount, 12) <= Fraction(pct, 100) * income
            assert accepted == expected, (amount, income)
