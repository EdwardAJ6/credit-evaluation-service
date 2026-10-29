import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.domain import Product
from app.main import app
from app.models import Application, Evaluation
from app.strategies.policies import get_policies
from tests.test_policies import ROWS

MAX_INT = 9007199254740991
JSON_HEADERS = {"content-type": "application/json"}
FIELDS = ("product", "amount", "monthly_income", "employment_months", "external_score")
INTEGER_FIELDS = FIELDS[1:]
APPLICATION_OUT_KEYS = {
    "id",
    *FIELDS,
    "status",
    "rejection_reasons",
    "created_at",
    "evaluated_at",
}

AC30 = ("TWIST", 4_200_000, 1_000_000, 0, 650)  # the AC-30 application


def body(case):
    values = AC30 if case == "AC30" else ROWS[case][:5]  # ROWS is in FIELDS order
    return dict(zip(FIELDS, values, strict=True))


def with_literal(field, literal):
    """Return R01 as JSON text with `field` set to a raw JSON literal such as 1e3."""
    text = json.dumps({**body("R01"), field: None})
    return text.replace(f'"{field}": null', f'"{field}": {literal}')


def without(case, field):
    return json.dumps({key: value for key, value in body(case).items() if key != field})


def create(client, case):
    response = client.post("/applications", json=body(case))
    assert response.status_code == 201
    return response.json()


def listing(client, **params):
    response = client.get("/applications", params=params)
    assert response.status_code == 200
    return response.json()


def codes(reasons):
    return [reason["code"] for reason in reasons]


def locs_422(response):
    """Assert a 422 whose body has the AC-42 shape; return its locs, the contract."""
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert isinstance(detail, list)
    for error in detail:
        assert {"type", "loc", "msg"} <= error.keys()
        assert "input" not in error
    return {tuple(error["loc"]) for error in detail}


def evaluations(session_factory):
    with session_factory() as db:
        return db.scalars(select(Evaluation).order_by(Evaluation.id)).all()


def assert_nothing_written(session_factory):
    with session_factory() as db:
        assert db.scalars(select(Application)).all() == []
        assert db.scalars(select(Evaluation)).all() == []


def use_stricter_twist_policy():
    stricter = replace(get_policies()[Product.TWIST], min_score=700)
    app.dependency_overrides[get_policies] = lambda: {
        **get_policies(),
        Product.TWIST: stricter,
    }
    # el teardown del fixture `client` limpia los overrides


INVALID_IDS = [
    pytest.param(value, id=f"E11-application_id={value}")
    for value in ("abc", "0", "-1", str(MAX_INT + 1), "9223372036854775808")
]

INVALID_QUERIES = [
    *(pytest.param("limit", value, id=f"E13-limit={value}") for value in (0, -1, 101)),
    *(
        pytest.param("offset", value, id=f"E13-offset={value}")
        for value in (-1, MAX_INT + 1)
    ),
    pytest.param("status", "FOO", id="E14-status=FOO"),
    pytest.param("product", "phone", id="E14-product=phone"),
    pytest.param("stauts", "REJECTED", id="E15-stauts=REJECTED"),
]

INVALID_LITERALS = [
    ("E01", "amount", ("0", "-1", str(MAX_INT + 1))),
    ("E02", "monthly_income", ("-1", str(MAX_INT + 1))),
    ("E03", "employment_months", ("-1", str(MAX_INT + 1))),
    ("E04", "external_score", ("-1", "1001")),
    ("E06", "product", ('"phone"', '"LOAN"', "null")),
    *(
        ("E07", field, ("true", '"1000"', "1000.0", "1e3", "null"))
        for field in INTEGER_FIELDS
    ),
    ("E08", "term_months", ("24",)),
]

INVALID_BODIES = [
    *(
        pytest.param(
            with_literal(field, literal),
            ("body", field),
            id=f"{case}-{field}={literal}",
        )
        for case, field, literals in INVALID_LITERALS
        for literal in literals
    ),
    pytest.param(
        without("R01", "product"), ("body", "product"), id="E06-product=absent"
    ),
    pytest.param('{"amount": ', ("body",), id="E10-body=malformed"),
    pytest.param("", ("body",), id="E10-body=empty"),
    pytest.param(
        without("R14", "employment_months"),
        ("body", "employment_months"),
        id="E23-employment_months=absent",
    ),
]

VALID_EDGES = {
    "amount": (1, MAX_INT),
    "monthly_income": (0, MAX_INT),
    "employment_months": (0, MAX_INT),
    "external_score": (0, 1000),
}


def test_ac10_post_creates_an_approved_application(client):
    response = client.post("/applications", json=body("R01"))
    assert response.status_code == 201
    created = response.json()
    assert created.keys() == APPLICATION_OUT_KEYS
    assert response.headers["location"] == f"/applications/{created['id']}"
    assert type(created["id"]) is int
    assert created["id"] >= 1
    assert {field: created[field] for field in FIELDS} == body("R01")
    assert created["status"] == "APPROVED"
    assert created["rejection_reasons"] == []


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        pytest.param("R03", ["SCORE_BELOW_MINIMUM"], id="R03"),
        pytest.param("R10", ["SCORE_BELOW_MINIMUM"], id="R10"),
        pytest.param("R16", ["SCORE_BELOW_MINIMUM", "INCOME_BELOW_MINIMUM"], id="R16"),
    ],
)
def test_ac11_post_creates_a_rejected_application(client, case, expected):
    response = client.post("/applications", json=body(case))
    assert response.status_code == 201
    created = response.json()
    assert response.headers["location"] == f"/applications/{created['id']}"
    assert created["status"] == "REJECTED"
    assert codes(created["rejection_reasons"]) == expected


@pytest.mark.parametrize("case", ["R01", "R06"])
def test_ac12_get_returns_the_posted_body(client, case):
    posted = client.post("/applications", json=body(case))
    assert posted.status_code == 201
    response = client.get(posted.headers["location"])
    assert response.status_code == 200
    assert response.json() == posted.json()


def test_ac13_post_timestamps_are_equal_utc_and_current(client):
    t0 = datetime.now(UTC)
    created = create(client, "R01")
    assert created["created_at"].endswith("Z")
    assert created["evaluated_at"].endswith("Z")
    created_at = datetime.fromisoformat(created["created_at"])
    assert datetime.fromisoformat(created["evaluated_at"]) == created_at
    assert abs(created_at - t0) < timedelta(seconds=60)


@pytest.mark.parametrize("application_id", INVALID_IDS)
def test_ac14_ac42_get_with_an_invalid_id_is_422(client, application_id):
    response = client.get(f"/applications/{application_id}")
    assert locs_422(response) == {("path", "application_id")}


@pytest.mark.parametrize(
    "application_id",
    [pytest.param(value, id=f"E12-application_id={value}") for value in (1, MAX_INT)],
)
def test_ac14_get_with_an_unknown_id_is_404(client, application_id):
    assert client.get(f"/applications/{application_id}").status_code == 404


def test_ac20_list_without_matches_is_empty(client):
    assert listing(client) == []
    create(client, "R01")
    assert listing(client, product="CARD") == []


def test_ac21_list_returns_the_posted_bodies_newest_first(client):
    first, second, third = [create(client, case) for case in ("R01", "R10", "R16")]
    assert listing(client) == [third, second, first]


def test_ac22_filters_combine_with_and(client):
    cases = ("R01", "R03", "R07", "R10", "R14", "R16")
    newest_first = [create(client, case) for case in cases][::-1]
    statuses = [{"status": status} for status in ("APPROVED", "REJECTED")]
    products = [{"product": product} for product in ("PHONE", "TWIST", "CARD")]
    combined = [{**status, **product} for status in statuses for product in products]
    for params in [*statuses, *products, *combined]:
        expected = [item for item in newest_first if params.items() <= item.items()]
        assert listing(client, **params) == expected, params


def test_ac23_pagination_returns_the_newest_first(client):
    newest_first = [create(client, "R01") for _ in range(51)][::-1]
    assert listing(client) == newest_first[:50]
    assert listing(client, limit=2, offset=1) == newest_first[1:3]
    assert listing(client, limit=100) == newest_first
    assert listing(client, limit=1) == newest_first[:1]
    assert listing(client, offset=MAX_INT) == []


@pytest.mark.parametrize(("name", "value"), INVALID_QUERIES)
def test_ac24_ac42_invalid_query_is_422(client, name, value):
    response = client.get("/applications", params={name: value})
    assert locs_422(response) == {("query", name)}


def test_ac30_reevaluate_without_policy_changes_keeps_the_decision(client):
    created = create(client, "AC30")
    response = client.post(f"/applications/{created['id']}/reevaluate")
    assert response.status_code == 200
    current = response.json()
    assert current["status"] == "APPROVED"
    assert {field: current[field] for field in FIELDS} == body("AC30")
    parse = datetime.fromisoformat
    assert parse(current["created_at"]) == parse(created["created_at"])
    assert parse(current["evaluated_at"]) >= parse(created["evaluated_at"])
    assert client.get(f"/applications/{created['id']}").json() == current


def test_ac31_reevaluate_applies_the_current_policy(client):
    created = create(client, "AC30")
    use_stricter_twist_policy()
    response = client.post(f"/applications/{created['id']}/reevaluate")
    assert response.status_code == 200
    current = response.json()
    assert current["status"] == "REJECTED"
    assert codes(current["rejection_reasons"]) == ["SCORE_BELOW_MINIMUM"]
    assert client.get(f"/applications/{created['id']}").json() == current
    assert listing(client, status="REJECTED") == [current]
    assert listing(client, status="APPROVED") == []


def test_ac32_reevaluate_with_an_unknown_id_is_404_and_writes_nothing(
    client, session_factory
):
    created = create(client, "AC30")
    for application_id in (created["id"] + 1, MAX_INT):
        response = client.post(f"/applications/{application_id}/reevaluate")
        assert response.status_code == 404, application_id
    assert len(evaluations(session_factory)) == 1


@pytest.mark.parametrize("application_id", INVALID_IDS)
def test_ac32_ac42_reevaluate_with_an_invalid_id_is_422(client, application_id):
    response = client.post(f"/applications/{application_id}/reevaluate")
    assert locs_422(response) == {("path", "application_id")}


def test_ac33_every_evaluation_is_recorded_with_its_policy(client, session_factory):
    created = create(client, "AC30")
    url = f"/applications/{created['id']}/reevaluate"
    assert client.post(url).status_code == 200
    use_stricter_twist_policy()
    response = client.post(url)
    assert response.status_code == 200
    current = response.json()
    history = evaluations(session_factory)
    assert [row.application_id for row in history] == [created["id"]] * 3
    assert [row.policy for row in history] == [
        {
            "name": "STANDARD",
            "min_score": min_score,
            "max_installment_pct": 35,
            "term_months": 12,
        }
        for min_score in (600, 600, 700)
    ]
    assert history[-1].status == current["status"]
    assert codes(history[-1].rejection_reasons) == codes(current["rejection_reasons"])


@pytest.mark.parametrize("case", ["R01", "R06"])
def test_ac34_post_records_exactly_one_evaluation(client, session_factory, case):
    created = create(client, case)
    history = evaluations(session_factory)
    assert [row.application_id for row in history] == [created["id"]]
    assert history[0].status == created["status"]
    assert codes(history[0].rejection_reasons) == codes(created["rejection_reasons"])


@pytest.mark.parametrize(("content", "loc"), INVALID_BODIES)
def test_ac40_ac42_invalid_body_is_422_and_writes_nothing(
    client, session_factory, content, loc
):
    response = client.post("/applications", content=content, headers=JSON_HEADERS)
    assert {error_loc[: len(loc)] for error_loc in locs_422(response)} == {loc}
    assert_nothing_written(session_factory)


@pytest.mark.parametrize(
    "literal",
    [
        pytest.param(literal, id=f"E09-amount={literal}")
        for literal in ("NaN", "Infinity", "-Infinity", "1e999")
    ],
)
def test_ac41_ac42_non_finite_amount_is_422_and_writes_nothing(
    client, session_factory, literal
):
    content = with_literal("amount", literal)
    response = client.post("/applications", content=content, headers=JSON_HEADERS)
    assert locs_422(response) == {("body", "amount")}
    assert_nothing_written(session_factory)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        pytest.param(field, value, id=f"E05-{field}={value}")
        for field, values in VALID_EDGES.items()
        for value in values
    ],
)
def test_ac43_valid_edge_is_created(client, field, value):
    response = client.post("/applications", json={**body("R01"), field: value})
    assert response.status_code == 201


def test_ac50_trailing_slash_is_404_without_redirect(client):
    response = client.get("/applications/", follow_redirects=False)
    assert response.status_code == 404
    assert "location" not in response.headers


def test_ac52_openapi_example_is_r01(client):
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    assert schemas["ApplicationCreate"]["examples"][0] == body("R01")
