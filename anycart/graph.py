"""The LangGraph agent: an LLM node that can call tools, looping until it answers.

    START -> agent --(tool calls?)--> tools -> agent ... -> END
"""

from __future__ import annotations

import os

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import SystemMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from anycart.tools import TOOLS

SYSTEM_PROMPT = """You are AnyCart's shopping assistant for an Australian online store.
Prices are in AUD. Shipping is free over A$100, otherwise A$9.95.
Use the tools to search products, manage the cart and check orders; never make up
products, prices, stock or order details. Before calling checkout, show the cart
total and ask the shopper to confirm. Keep answers short."""


def bedrock_llm() -> BaseChatModel:
    """Claude on Amazon Bedrock via the Converse API.

    BEDROCK_MODEL_ID is the model or inference-profile ID shown in the Bedrock
    console (Model catalog). AWS credentials come from the usual AWS chain
    (aws configure, env vars or an IAM role).
    """
    from langchain_aws import ChatBedrockConverse

    model_id = os.environ.get("BEDROCK_MODEL_ID")
    if not model_id:
        raise RuntimeError("Set BEDROCK_MODEL_ID in .env (see README step 3).")
    return ChatBedrockConverse(
        model=model_id,
        region_name=os.environ.get("AWS_REGION", "ap-southeast-2"),
        max_tokens=4096,
    )


def text_of(message) -> str:
    """Final answer text. Bedrock Converse may return a list of content blocks."""
    content = message.content
    if isinstance(content, list):
        return "".join(b.get("text", "") for b in content if isinstance(b, dict))
    return content


def build_graph(llm: BaseChatModel | None = None, checkpointer=None):
    llm_with_tools = (llm or bedrock_llm()).bind_tools(TOOLS)

    def agent(state: MessagesState):
        messages = [SystemMessage(SYSTEM_PROMPT), *state["messages"]]
        return {"messages": [llm_with_tools.invoke(messages)]}

    graph = StateGraph(MessagesState)
    graph.add_node("agent", agent)
    graph.add_node("tools", ToolNode(TOOLS))
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", tools_condition)
    graph.add_edge("tools", "agent")
    # The checkpointer keeps each conversation's history, keyed by thread_id.
    return graph.compile(checkpointer=checkpointer or InMemorySaver())
