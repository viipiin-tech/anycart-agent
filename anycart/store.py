"""In-memory catalogue, carts and orders.

A real shop would use a database. Keeping it in memory makes the agent easy
to run and test; swap this module for DynamoDB later (see README exercises).
"""

from __future__ import annotations

import itertools
import json
from dataclasses import dataclass, field
from pathlib import Path

DATA_FILE = Path(__file__).parent / "data" / "products.json"
FREE_SHIPPING_OVER = 100.0
SHIPPING_FEE = 9.95


@dataclass
class Order:
    order_id: str
    items: dict[str, int]
    total: float
    status: str = "processing"


@dataclass
class Store:
    products: dict[str, dict] = field(default_factory=dict)
    carts: dict[str, dict[str, int]] = field(default_factory=dict)
    orders: dict[str, Order] = field(default_factory=dict)
    _ids: itertools.count = field(default_factory=lambda: itertools.count(1001))

    @classmethod
    def load(cls) -> "Store":
        products = {p["sku"]: p for p in json.loads(DATA_FILE.read_text())}
        store = cls(products=products)
        # Two sample orders so "where is my order?" works straight away.
        store.orders["ORD-0901"] = Order("ORD-0901", {"AC-202": 1}, 48.95, "shipped")
        store.orders["ORD-0902"] = Order("ORD-0902", {"AC-103": 1}, 249.0, "delivered")
        return store

    # Catalogue -------------------------------------------------------------
    def search(self, query: str = "", category: str | None = None, max_price: float | None = None) -> list[dict]:
        words = query.lower().split()
        results = []
        for p in self.products.values():
            text = f"{p['name']} {p['description']} {p['category']}".lower()
            if words and not all(w in text for w in words):
                continue
            if category and p["category"] != category.lower():
                continue
            if max_price is not None and p["price"] > max_price:
                continue
            results.append(p)
        return sorted(results, key=lambda p: p["price"])

    # Cart ------------------------------------------------------------------
    def cart(self, cart_id: str) -> dict[str, int]:
        return self.carts.setdefault(cart_id, {})

    def add(self, cart_id: str, sku: str, qty: int) -> str:
        product = self.products.get(sku)
        if product is None:
            return f"No product with SKU {sku}."
        if qty < 1:
            return "Quantity must be at least 1."
        cart = self.cart(cart_id)
        wanted = cart.get(sku, 0) + qty
        if wanted > product["stock"]:
            return f"Only {product['stock']} of {product['name']} in stock."
        cart[sku] = wanted
        return f"Added {qty} x {product['name']}. Cart now has {wanted} of it."

    def remove(self, cart_id: str, sku: str) -> str:
        cart = self.cart(cart_id)
        if cart.pop(sku, None) is None:
            return f"{sku} is not in the cart."
        return f"Removed {self.products[sku]['name']} from the cart."

    def summary(self, cart_id: str) -> dict:
        cart = self.cart(cart_id)
        lines = [
            {"sku": sku, "name": self.products[sku]["name"], "qty": qty,
             "line_total": round(self.products[sku]["price"] * qty, 2)}
            for sku, qty in cart.items()
        ]
        subtotal = round(sum(line["line_total"] for line in lines), 2)
        shipping = 0.0 if subtotal == 0 or subtotal >= FREE_SHIPPING_OVER else SHIPPING_FEE
        return {"items": lines, "subtotal": subtotal, "shipping": shipping,
                "total": round(subtotal + shipping, 2)}

    # Orders ----------------------------------------------------------------
    def checkout(self, cart_id: str) -> str:
        summary = self.summary(cart_id)
        if not summary["items"]:
            return "The cart is empty."
        cart = self.cart(cart_id)
        for sku, qty in cart.items():
            if qty > self.products[sku]["stock"]:
                return f"Not enough stock for {self.products[sku]['name']}."
        for sku, qty in cart.items():
            self.products[sku]["stock"] -= qty
        order_id = f"ORD-{next(self._ids)}"
        self.orders[order_id] = Order(order_id, dict(cart), summary["total"])
        cart.clear()
        return f"Order {order_id} placed. Total A${summary['total']:.2f}."

    def order_status(self, order_id: str) -> str:
        order = self.orders.get(order_id.upper())
        if order is None:
            return f"No order {order_id}."
        return f"Order {order.order_id}: {order.status}, total A${order.total:.2f}."
