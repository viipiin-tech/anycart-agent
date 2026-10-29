"""FastAPI service for the AnyCart agent. Runs locally with uvicorn and on AWS Lambda through Mangum (handler.py).

    POST /chat                 {"message": "...", "thread_id": optional}  -> reply, tools used, cart
    GET  /cart/{thread_id}     cart summary
    GET  /orders/{order_id}    order status
    GET  /health               liveness and storage backend

When ANYCART_API_KEY is set, every route except /health needs the header x-api-key.
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import time
import uuid
from functools import lru_cache

from fastapi import Depends, FastAPI, Header, HTTPException, Path, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from anycart.service import chat_turn
from anycart.tools import STORE

logger = logging.getLogger("anycart.api")
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

THREAD_ID = r"^[A-Za-z0-9_-]{8,64}$"

app = FastAPI(title="AnyCart Agent API", version="1.0.0")


# ---------------------------------------------------------------- models
class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    thread_id: str | None = Field(default=None, pattern=THREAD_ID, description="Omit to start a new conversation.")


class CartLine(BaseModel):
    sku: str
    name: str
    qty: int
    line_total: float


class Cart(BaseModel):
    items: list[CartLine]
    subtotal: float
    shipping: float
    total: float


class ChatResponse(BaseModel):
    thread_id: str
    reply: str
    tools_used: list[str]
    cart: Cart
    latency_ms: int


class OrderOut(BaseModel):
    order_id: str
    status: str
    total: float
    items: dict[str, int]


# ---------------------------------------------------------- dependencies
def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    expected = os.environ.get("ANYCART_API_KEY", "")
    if expected and not hmac.compare_digest(x_api_key or "", expected):
        raise HTTPException(status_code=401, detail="Missing or wrong x-api-key header.")


@lru_cache(maxsize=1)
def get_agent():
    """Built once per Lambda container (warm invocations reuse it)."""
    from anycart.graph import build_graph

    return build_graph(memory=False)


def agent_provider():
    """Returns the factory, not the agent: the model is only set up once a request has
    passed validation, and a setup error (e.g. no model ID) becomes a 502, not a 500."""
    return get_agent


def get_store():
    return STORE


def log(event: str, **fields) -> None:
    """One JSON line per event, easy to query in CloudWatch Logs Insights."""
    logger.info(json.dumps({"event": event, **fields}))


# ---------------------------------------------------------------- routes
@app.get("/health")
def health(store=Depends(get_store)):
    return {"status": "ok", "storage": store.repo.kind}


@app.post("/chat", response_model=ChatResponse, dependencies=[Depends(require_api_key)])
def chat(body: ChatRequest, agent_factory=Depends(agent_provider), store=Depends(get_store)):
    thread_id = body.thread_id or uuid.uuid4().hex
    started = time.perf_counter()
    try:
        turn = chat_turn(agent_factory(), store, thread_id, body.message)
    except Exception as err:  # model or AWS failure: report it without leaking details
        log("chat_failed", thread_id=thread_id, error=type(err).__name__)
        raise HTTPException(status_code=502, detail="The assistant is unavailable right now. Please try again.") from err
    latency_ms = int((time.perf_counter() - started) * 1000)
    log("chat", thread_id=thread_id, latency_ms=latency_ms, tools=turn.tools_used, storage=store.repo.kind)
    return ChatResponse(thread_id=thread_id, reply=turn.reply, tools_used=turn.tools_used,
                        cart=store.summary(thread_id), latency_ms=latency_ms)


@app.get("/cart/{thread_id}", response_model=Cart, dependencies=[Depends(require_api_key)])
def get_cart(thread_id: str = Path(pattern=THREAD_ID), store=Depends(get_store)):
    return store.summary(thread_id)


@app.get("/orders/{order_id}", response_model=OrderOut, dependencies=[Depends(require_api_key)])
def get_order(order_id: str = Path(pattern=r"^[A-Za-z]{3}-\d{3,10}$"), store=Depends(get_store)):
    order = store.get_order(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail=f"No order {order_id}.")
    return OrderOut(order_id=order.order_id, status=order.status, total=order.total, items=order.items)


@app.exception_handler(Exception)
async def unhandled(request: Request, err: Exception):
    log("unhandled_error", path=request.url.path, error=type(err).__name__)
    return JSONResponse(status_code=500, content={"detail": "Internal error."})
