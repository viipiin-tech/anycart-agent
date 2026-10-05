"""Tools the agent can call. Each one is a thin wrapper over the Store.

The cart is keyed by the LangGraph thread_id, which LangChain injects through
the RunnableConfig argument (the model never sees or fills that argument).
"""

from __future__ import annotations

import json

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from anycart.store import Store

STORE = Store.load()


def _cart_id(config: RunnableConfig) -> str:
    return (config.get("configurable") or {}).get("thread_id", "default")


@tool
def search_products(query: str = "", category: str | None = None, max_price: float | None = None) -> str:
    """Search the AnyCart catalogue.

    Args:
        query: words to match in the product name or description, e.g. "earbuds".
        category: one of electronics, sport, kitchen, bags.
        max_price: highest price in AUD.
    """
    results = STORE.search(query, category, max_price)
    if not results:
        return "No matching products."
    return json.dumps(results)


@tool
def add_to_cart(sku: str, quantity: int, config: RunnableConfig) -> str:
    """Add a product to the shopper's cart by SKU (e.g. AC-101)."""
    return STORE.add(_cart_id(config), sku.upper(), quantity)


@tool
def remove_from_cart(sku: str, config: RunnableConfig) -> str:
    """Remove a product from the shopper's cart by SKU."""
    return STORE.remove(_cart_id(config), sku.upper())


@tool
def view_cart(config: RunnableConfig) -> str:
    """Show the cart: items, subtotal, shipping and total in AUD."""
    return json.dumps(STORE.summary(_cart_id(config)))


@tool
def checkout(config: RunnableConfig) -> str:
    """Place the order for everything in the cart. Only call after the shopper confirms."""
    return STORE.checkout(_cart_id(config))


@tool
def order_status(order_id: str) -> str:
    """Look up an order's status by ID, e.g. ORD-0901."""
    return STORE.order_status(order_id)


TOOLS = [search_products, add_to_cart, remove_from_cart, view_cart, checkout, order_status]
