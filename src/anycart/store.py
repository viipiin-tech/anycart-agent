"""The shop's rules: catalogue search, cart limits, shipping and checkout.

Prices and stock checks are enforced here, in code, never left to the model.
Where carts, orders and stock are saved is up to the repository (in memory by
default, DynamoDB when ANYCART_TABLE is set; see repository.py).
"""

from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from anycart.repository import DynamoRepository, MemoryRepository, Order, OutOfStock, Repository

DATA_FILE = Path(__file__).parent / "data" / "products.json"
FREE_SHIPPING_OVER = 100.0
SHIPPING_FEE = 9.95

# Two read-only sample orders so "where is my order?" works straight away.
SAMPLE_ORDERS = {
    "ORD-0901": Order("ORD-0901", {"AC-202": 1}, 48.95, "shipped"),
    "ORD-0902": Order("ORD-0902", {"AC-103": 1}, 249.0, "delivered"),
}


@dataclass
class Store:
    products: dict[str, dict]
    repo: Repository = field(default_factory=MemoryRepository)

    @classmethod
    def load(cls, repo: Repository | None = None) -> "Store":
        products = {p["sku"]: p for p in json.loads(DATA_FILE.read_text())}
        return cls(products=copy.deepcopy(products), repo=repo or MemoryRepository())

    @classmethod
    def from_env(cls) -> "Store":
        """DynamoDB when ANYCART_TABLE is set (Lambda), otherwise in memory."""
        table = os.environ.get("ANYCART_TABLE")
        return cls.load(DynamoRepository(table) if table else None)

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
            results.append(dict(p))
        stocks = self.repo.get_stocks(self.products, [p["sku"] for p in results])
        for p in results:
            p["stock"] = stocks[p["sku"]]
        return sorted(results, key=lambda p: p["price"])

    # Cart ------------------------------------------------------------------
    def cart(self, cart_id: str) -> dict[str, int]:
        return self.repo.get_cart(cart_id)

    def add(self, cart_id: str, sku: str, qty: int) -> str:
        product = self.products.get(sku)
        if product is None:
            return f"No product with SKU {sku}."
        if qty < 1:
            return "Quantity must be at least 1."
        cart = self.cart(cart_id)
        wanted = cart.get(sku, 0) + qty
        stock = self.repo.get_stocks(self.products, [sku])[sku]
        if wanted > stock:
            return f"Only {stock} of {product['name']} in stock."
        cart[sku] = wanted
        self.repo.put_cart(cart_id, cart)
        return f"Added {qty} x {product['name']}. Cart now has {wanted} of it."

    def remove(self, cart_id: str, sku: str) -> str:
        cart = self.cart(cart_id)
        if cart.pop(sku, None) is None:
            return f"{sku} is not in the cart."
        self.repo.put_cart(cart_id, cart)
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
        order = Order(self.repo.next_order_id(), self.cart(cart_id), summary["total"])
        try:
            self.repo.place_order(cart_id, order, self.products)
        except OutOfStock:
            return "Not enough stock for one of the items in your cart. Please check the cart and try again."
        return f"Order {order.order_id} placed. Total A${summary['total']:.2f}."

    def get_order(self, order_id: str) -> Order | None:
        order_id = order_id.upper()
        return self.repo.get_order(order_id) or SAMPLE_ORDERS.get(order_id)

    def order_status(self, order_id: str) -> str:
        order = self.get_order(order_id)
        if order is None:
            return f"No order {order_id}."
        return f"Order {order.order_id}: {order.status}, total A${order.total:.2f}."
