"""DynamoDB storage against moto (an in-process AWS mock): no AWS account needed."""

import boto3
import pytest
from moto import mock_aws

from anycart.repository import DynamoRepository
from anycart.store import Store

TABLE = "anycart-test"


@pytest.fixture
def store():
    with mock_aws():
        client = boto3.client("dynamodb", region_name="ap-southeast-2")
        client.create_table(
            TableName=TABLE, BillingMode="PAY_PER_REQUEST",
            AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}, {"AttributeName": "sk", "AttributeType": "S"}],
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}],
        )
        yield Store.load(DynamoRepository(TABLE, client=client))


def test_cart_is_saved_and_cleared(store):
    store.add("t1", "AC-202", 2)
    assert store.summary("t1")["subtotal"] == 78.0
    store.remove("t1", "AC-202")
    assert store.summary("t1")["items"] == []


def test_checkout_is_one_transaction(store):
    store.add("t2", "AC-101", 2)
    message = store.checkout("t2")
    order_id = message.split()[1]
    assert order_id == "ORD-1001"
    assert store.get_order(order_id).items == {"AC-101": 2}
    assert store.summary("t2")["items"] == []
    assert store.search("earbuds")[0]["stock"] == 23  # 25 in the catalogue, 2 sold


def test_checkout_refuses_when_stock_ran_out_and_changes_nothing(store):
    store.add("a", "AC-203", 1)
    store.add("b", "AC-203", 1)
    stock = store.search("water bottle")[0]["stock"]
    # Someone else buys the rest before "b" checks out.
    store.repo.client.put_item(TableName=TABLE, Item={"pk": {"S": "STOCK#AC-203"}, "sk": {"S": "STOCK"}, "stock": {"N": "0"}})
    assert store.checkout("b").startswith("Not enough stock")
    assert store.summary("b")["items"][0]["sku"] == "AC-203"  # cart kept
    assert store.repo.get_order("ORD-1001") is None  # no order written
    assert stock > 0


def test_order_numbers_count_up(store):
    assert [store.repo.next_order_id() for _ in range(3)] == ["ORD-1001", "ORD-1002", "ORD-1003"]


def test_chat_history_round_trip(store):
    msgs = [{"type": "human", "data": {"content": "hi"}}]
    store.repo.put_history("t3", msgs)
    assert store.repo.get_history("t3") == msgs
    assert store.repo.get_history("none") == []
