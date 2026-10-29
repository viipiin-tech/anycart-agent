"""Where carts, orders, stock and chat history live.

The Store holds the shop's rules; a repository only saves and loads. Two
implementations share one interface:

- MemoryRepository: a dict, for the CLI, Streamlit and the tests.
- DynamoRepository: one DynamoDB table (single-table design), for AWS Lambda,
  where memory is lost between invocations.

DynamoDB items (pk / sk):

    CART#<thread_id>   CART      items: {sku: qty}             (expires after 7 days)
    CHAT#<thread_id>   HISTORY   messages: JSON string          (expires after 7 days)
    ORDER#<order_id>   ORDER     items, total, status
    STOCK#<sku>        STOCK     stock (created on first checkout from the catalogue figure)
    COUNTER            ORDER     seq (atomic counter for order numbers)
"""

from __future__ import annotations

import itertools
import json
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

TTL_SECONDS = 7 * 24 * 3600


@dataclass
class Order:
    order_id: str
    items: dict[str, int]
    total: float
    status: str = "processing"


class OutOfStock(Exception):
    """Raised by place_order when any line has less stock than ordered."""


class Repository(Protocol):
    kind: str

    def get_cart(self, cart_id: str) -> dict[str, int]: ...
    def put_cart(self, cart_id: str, items: dict[str, int]) -> None: ...
    def get_stocks(self, catalogue: dict[str, dict], skus: list[str]) -> dict[str, int]: ...
    def next_order_id(self) -> str: ...
    def place_order(self, cart_id: str, order: Order, catalogue: dict[str, dict]) -> None: ...
    def get_order(self, order_id: str) -> Order | None: ...
    def get_history(self, thread_id: str) -> list[dict]: ...
    def put_history(self, thread_id: str, messages: list[dict]) -> None: ...


class MemoryRepository:
    """Keeps everything in this process. Stock is read from and written to the catalogue dict."""

    kind = "memory"

    def __init__(self) -> None:
        self.carts: dict[str, dict[str, int]] = {}
        self.orders: dict[str, Order] = {}
        self.history: dict[str, list[dict]] = {}
        self._ids = itertools.count(1001)

    def get_cart(self, cart_id):
        return dict(self.carts.get(cart_id, {}))

    def put_cart(self, cart_id, items):
        self.carts[cart_id] = dict(items)

    def get_stocks(self, catalogue, skus):
        return {sku: catalogue[sku]["stock"] for sku in skus}

    def next_order_id(self):
        return f"ORD-{next(self._ids)}"

    def place_order(self, cart_id, order, catalogue):
        if any(qty > catalogue[sku]["stock"] for sku, qty in order.items.items()):
            raise OutOfStock
        for sku, qty in order.items.items():
            catalogue[sku]["stock"] -= qty
        self.orders[order.order_id] = order
        self.carts.pop(cart_id, None)

    def get_order(self, order_id):
        return self.orders.get(order_id)

    def get_history(self, thread_id):
        return list(self.history.get(thread_id, []))

    def put_history(self, thread_id, messages):
        self.history[thread_id] = list(messages)


class DynamoRepository:
    """Single-table DynamoDB storage. Checkout is one transaction: stock, order and cart change together or not at all."""

    kind = "dynamodb"

    def __init__(self, table_name: str, client=None) -> None:
        import boto3

        self.table_name = table_name
        self.client = client or boto3.client("dynamodb")

    # Small helpers for DynamoDB's typed attribute format ---------------------
    @staticmethod
    def _key(pk: str, sk: str) -> dict:
        return {"pk": {"S": pk}, "sk": {"S": sk}}

    @staticmethod
    def _expires() -> dict:
        return {"N": str(int(time.time()) + TTL_SECONDS)}

    def _get(self, pk: str, sk: str) -> dict | None:
        return self.client.get_item(TableName=self.table_name, Key=self._key(pk, sk), ConsistentRead=True).get("Item")

    # Carts ------------------------------------------------------------------
    def get_cart(self, cart_id):
        item = self._get(f"CART#{cart_id}", "CART")
        if not item:
            return {}
        return {sku: int(v["N"]) for sku, v in item["items"]["M"].items()}

    def put_cart(self, cart_id, items):
        if not items:
            self.client.delete_item(TableName=self.table_name, Key=self._key(f"CART#{cart_id}", "CART"))
            return
        self.client.put_item(TableName=self.table_name, Item={
            **self._key(f"CART#{cart_id}", "CART"),
            "items": {"M": {sku: {"N": str(qty)} for sku, qty in items.items()}},
            "expires_at": self._expires(),
        })

    # Stock ------------------------------------------------------------------
    def get_stocks(self, catalogue, skus):
        stocks = {sku: catalogue[sku]["stock"] for sku in skus}
        if not skus:
            return stocks
        keys = [self._key(f"STOCK#{sku}", "STOCK") for sku in dict.fromkeys(skus)]
        for start in range(0, len(keys), 100):  # BatchGetItem takes up to 100 keys
            resp = self.client.batch_get_item(RequestItems={self.table_name: {"Keys": keys[start:start + 100], "ConsistentRead": True}})
            for item in resp["Responses"].get(self.table_name, []):
                stocks[item["pk"]["S"].removeprefix("STOCK#")] = int(item["stock"]["N"])
        return stocks

    # Orders -----------------------------------------------------------------
    def next_order_id(self):
        resp = self.client.update_item(
            TableName=self.table_name, Key=self._key("COUNTER", "ORDER"),
            UpdateExpression="ADD seq :one", ExpressionAttributeValues={":one": {"N": "1"}},
            ReturnValues="UPDATED_NEW",
        )
        return f"ORD-{1000 + int(resp['Attributes']['seq']['N'])}"

    def place_order(self, cart_id, order, catalogue):
        stock_updates = [{
            "Update": {
                "TableName": self.table_name,
                "Key": self._key(f"STOCK#{sku}", "STOCK"),
                # First sale of a SKU starts from the catalogue figure; after that the stored figure counts.
                "UpdateExpression": "SET stock = if_not_exists(stock, :initial) - :qty",
                "ConditionExpression": "(attribute_not_exists(stock) AND :initial >= :qty) OR stock >= :qty",
                "ExpressionAttributeValues": {":initial": {"N": str(catalogue[sku]["stock"])}, ":qty": {"N": str(qty)}},
            }
        } for sku, qty in order.items.items()]
        put_order = {"Put": {"TableName": self.table_name, "Item": {
            **self._key(f"ORDER#{order.order_id}", "ORDER"),
            "items": {"M": {sku: {"N": str(qty)} for sku, qty in order.items.items()}},
            "total": {"N": str(Decimal(str(order.total)))},
            "status": {"S": order.status},
        }}}
        clear_cart = {"Delete": {"TableName": self.table_name, "Key": self._key(f"CART#{cart_id}", "CART")}}
        try:
            self.client.transact_write_items(TransactItems=[*stock_updates, put_order, clear_cart])
        except self.client.exceptions.TransactionCanceledException as err:
            reasons = [r.get("Code") for r in err.response.get("CancellationReasons", [])]
            if "ConditionalCheckFailed" in reasons:
                raise OutOfStock from err
            raise

    def get_order(self, order_id):
        item = self._get(f"ORDER#{order_id}", "ORDER")
        if not item:
            return None
        return Order(
            order_id=order_id,
            items={sku: int(v["N"]) for sku, v in item["items"]["M"].items()},
            total=float(item["total"]["N"]),
            status=item["status"]["S"],
        )

    # Chat history -----------------------------------------------------------
    def get_history(self, thread_id):
        item = self._get(f"CHAT#{thread_id}", "HISTORY")
        return json.loads(item["messages"]["S"]) if item else []

    def put_history(self, thread_id, messages):
        self.client.put_item(TableName=self.table_name, Item={
            **self._key(f"CHAT#{thread_id}", "HISTORY"),
            "messages": {"S": json.dumps(messages)},
            "expires_at": self._expires(),
        })
