"""Runs the whole graph offline with a scripted fake model (no AWS needed)."""

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from anycart.graph import build_graph, text_of
from anycart.tools import STORE


class ScriptedModel(BaseChatModel):
    """Returns the next scripted reply on each call."""

    replies: list

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=self.replies.pop(0))])


def test_agent_searches_then_adds_to_cart():
    model = ScriptedModel(replies=[
        AIMessage("", tool_calls=[{"name": "search_products", "args": {"query": "yoga"}, "id": "1"}]),
        AIMessage("", tool_calls=[{"name": "add_to_cart", "args": {"sku": "AC-202", "quantity": 1}, "id": "2"}]),
        AIMessage("Added the Yoga Mat (A$39.00) to your cart."),
    ])
    app = build_graph(llm=model)
    config = {"configurable": {"thread_id": "test-thread"}}
    result = app.invoke({"messages": [("user", "add a yoga mat")]}, config)

    tool_outputs = [m.content for m in result["messages"] if m.type == "tool"]
    assert "AC-202" in tool_outputs[0]
    assert tool_outputs[1].startswith("Added 1 x Yoga Mat")
    assert STORE.summary("test-thread")["items"][0]["sku"] == "AC-202"
    assert text_of(result["messages"][-1]).startswith("Added the Yoga Mat")
