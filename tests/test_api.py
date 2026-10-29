"""The FastAPI service, offline: a scripted model and the in-memory store."""

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from anycart.api import agent_provider, app, get_store
from anycart.graph import build_graph
from anycart.store import Store
from tests.fakes import ScriptedModel


@pytest.fixture
def store(monkeypatch):
    # The tools read anycart.tools.STORE, so the API and the tools must share one store.
    fresh = Store.load()
    monkeypatch.setattr("anycart.tools.STORE", fresh)
    app.dependency_overrides[get_store] = lambda: fresh
    yield fresh
    app.dependency_overrides.clear()


def client_with(model) -> TestClient:
    agent = build_graph(llm=model, memory=False)
    app.dependency_overrides[agent_provider] = lambda: (lambda: agent)
    return TestClient(app)


def test_chat_runs_tools_and_returns_the_cart(store):
    model = ScriptedModel(replies=[
        AIMessage("", tool_calls=[{"name": "add_to_cart", "args": {"sku": "AC-202", "quantity": 2}, "id": "1"}]),
        AIMessage("Added two yoga mats."),
    ])
    r = client_with(model).post("/chat", json={"message": "two yoga mats please"})
    assert r.status_code == 200
    body = r.json()
    assert body["reply"] == "Added two yoga mats."
    assert body["tools_used"] == ["add_to_cart"]
    assert body["cart"]["items"][0] == {"sku": "AC-202", "name": "Yoga Mat", "qty": 2, "line_total": 78.0}
    assert body["cart"]["shipping"] == 9.95
    assert len(body["thread_id"]) >= 8


def test_history_is_saved_between_turns(store):
    model = ScriptedModel(replies=[AIMessage("Hi! What are you after?"), AIMessage("Sure, earbuds.")])
    client = client_with(model)
    first = client.post("/chat", json={"message": "hello"}).json()
    client.post("/chat", json={"message": "earbuds", "thread_id": first["thread_id"]})
    sent = [m.content for m in model.seen[-1]]
    assert sent[-3:] == ["hello", "Hi! What are you after?", "earbuds"]
    assert len(store.repo.get_history(first["thread_id"])) == 4


def test_cart_and_order_endpoints(store):
    client = TestClient(app)
    store.add("thread-0001", "AC-101", 1)
    assert client.get("/cart/thread-0001").json()["subtotal"] == 89.0
    assert client.get("/orders/ORD-0901").json()["status"] == "shipped"
    assert client.get("/orders/ORD-9999").status_code == 404


def test_validation_rejects_bad_input(store):
    client = TestClient(app)
    assert client.post("/chat", json={"message": ""}).status_code == 422
    assert client.post("/chat", json={"message": "hi", "thread_id": "bad id!"}).status_code == 422
    assert client.get("/cart/x").status_code == 422


def test_api_key_is_required_when_configured(store, monkeypatch):
    monkeypatch.setenv("ANYCART_API_KEY", "s3cret-key")
    client = TestClient(app)
    assert client.get("/cart/thread-0001").status_code == 401
    assert client.get("/cart/thread-0001", headers={"x-api-key": "wrong"}).status_code == 401
    assert client.get("/cart/thread-0001", headers={"x-api-key": "s3cret-key"}).status_code == 200
    assert client.get("/health").status_code == 200  # health stays open for monitoring


def test_model_failure_returns_502_without_details(store):
    class Broken(ScriptedModel):
        def _generate(self, *args, **kwargs):
            raise RuntimeError("AccessDeniedException: arn:aws:bedrock:secret")

    r = client_with(Broken(replies=[])).post("/chat", json={"message": "hi"})
    assert r.status_code == 502
    assert "arn" not in r.text


def test_lambda_handler_serves_an_api_gateway_event(store):
    from anycart.handler import handler

    event = {
        "version": "2.0", "routeKey": "$default", "rawPath": "/health", "rawQueryString": "",
        "headers": {"host": "example.com"},
        "requestContext": {"http": {"method": "GET", "path": "/health", "protocol": "HTTP/1.1", "sourceIp": "1.2.3.4", "userAgent": "pytest"},
                           "requestId": "id", "routeKey": "$default", "stage": "$default", "accountId": "123", "apiId": "api",
                           "domainName": "example.com", "domainPrefix": "example", "time": "now", "timeEpoch": 0},
        "isBase64Encoded": False,
    }
    response = handler(event, None)
    assert response["statusCode"] == 200
    assert '"status":"ok"' in response["body"]
