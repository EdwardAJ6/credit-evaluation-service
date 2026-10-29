import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.main import app
from app.models import Application, Evaluation
from tests.test_applications_api import MAX_INT, assert_nothing_written, body, create

# Requests without a key go through TestClient(app); another key goes in the
# request headers (spec section 7.3).
CREDENTIALS = [
    pytest.param(None, id="E25-X-API-Key=absent"),
    pytest.param({"X-API-Key": "wrong-key"}, id="E26-X-API-Key=wrong-key"),
    pytest.param({"X-API-Key": ""}, id="E26-X-API-Key=empty"),
    # first characters of the API_KEY set by the `client` fixture
    pytest.param({"X-API-Key": "test-api"}, id="E26-X-API-Key=prefix"),
]

ROUTES = [
    pytest.param(method, route, payload, id=f"E25-route={method} {route}")
    for method, route, payload in (
        ("POST", "/applications", body("R01")),
        ("GET", "/applications/{application_id}", None),
        ("GET", "/applications", None),
        ("POST", "/applications/{application_id}/reevaluate", None),
    )
]


def assert_401(response):
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "ApiKey"


def row_counts(session_factory):
    with session_factory() as db:
        return [
            db.scalar(select(func.count()).select_from(model))
            for model in (Application, Evaluation)
        ]


@pytest.mark.parametrize(("method", "route", "payload"), ROUTES)
@pytest.mark.parametrize("headers", CREDENTIALS)
def test_ac70_route_without_a_valid_key_is_401_and_writes_nothing(
    client, session_factory, method, route, payload, headers
):
    created = create(client, "R01")
    before = row_counts(session_factory)
    url = route.format(application_id=created["id"])
    assert_401(TestClient(app).request(method, url, json=payload, headers=headers))
    assert row_counts(session_factory) == before


@pytest.mark.usefixtures("client")
def test_ac71_non_ascii_key_is_401():
    assert_401(TestClient(app).get("/applications", headers={"X-API-Key": b"\xf1"}))


@pytest.mark.usefixtures("client")
@pytest.mark.parametrize(
    "amount",
    [pytest.param(value, id=f"E01-amount={value}") for value in (0, -1, MAX_INT + 1)],
)
def test_ac72_invalid_body_without_key_is_401_not_422(session_factory, amount):
    invalid = {**body("R01"), "amount": amount}
    assert_401(TestClient(app).post("/applications", json=invalid))
    assert_nothing_written(session_factory)


@pytest.mark.usefixtures("client")
@pytest.mark.parametrize(
    "path",
    [
        pytest.param(path, id=f"E29-path={path}")
        for path in ("/health", "/openapi.json")
    ],
)
def test_ac73_public_route_without_key_is_200(path):
    assert TestClient(app).get(path).status_code == 200


@pytest.mark.usefixtures("client")
def test_ac73_openapi_declares_the_api_key_header_scheme():
    openapi = TestClient(app).get("/openapi.json").json()
    expected = {"type": "apiKey", "in": "header", "name": "X-API-Key"}.items()
    schemes = openapi["components"]["securitySchemes"].values()
    assert any(expected <= scheme.items() for scheme in schemes)
