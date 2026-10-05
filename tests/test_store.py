from anycart.store import Store


def test_search_filters_by_words_category_and_price():
    store = Store.load()
    assert [p["sku"] for p in store.search("earbuds")] == ["AC-101"]
    assert all(p["category"] == "kitchen" for p in store.search(category="kitchen"))
    assert all(p["price"] <= 50 for p in store.search(max_price=50))


def test_cart_respects_stock_and_shipping():
    store = Store.load()
    assert "out" not in store.add("t1", "AC-202", 2)
    assert store.add("t1", "AC-104", 1).startswith("Only 0")  # out of stock
    summary = store.summary("t1")
    assert summary["subtotal"] == 78.0 and summary["shipping"] == 9.95
    store.add("t1", "AC-203", 1)
    assert store.summary("t1")["shipping"] == 0.0  # free over A$100


def test_checkout_creates_order_and_empties_cart():
    store = Store.load()
    store.add("t2", "AC-101", 1)
    message = store.checkout("t2")
    order_id = message.split()[1]
    assert store.summary("t2")["items"] == []
    assert "processing" in store.order_status(order_id)
    assert store.products["AC-101"]["stock"] == 24
    assert store.checkout("t2") == "The cart is empty."
