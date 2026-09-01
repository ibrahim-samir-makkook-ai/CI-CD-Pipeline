import pytest
from app import app, add


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def test_home_status_code(client):
    response = client.get("/")
    assert response.status_code == 200


def test_home_message(client):
    response = client.get("/")
    data = response.get_json()
    assert data["message"] == "Hello, CI/CD Pipeline!"


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_add_unit():
    assert add(2, 3) == 5
    assert add(-1, 1) == 0
    assert add(0, 0) == 0


def test_add_route(client):
    response = client.get("/add/4/6")
    assert response.status_code == 200
    data = response.get_json()
    assert data["result"] == 10
    assert data["a"] == 4
    assert data["b"] == 6
