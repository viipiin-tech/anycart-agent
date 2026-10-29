"""One chat turn for the API: load the conversation, run the agent, save it back.

The API compiles the graph without a checkpointer (a Lambda's memory doesn't
survive between invocations), so the history is stored in the repository and
passed in on every turn.
"""

from __future__ import annotations

from dataclasses import dataclass

from langchain_core.messages import HumanMessage, messages_from_dict, messages_to_dict

from anycart.graph import text_of
from anycart.store import Store

# Keep the prompt (and the DynamoDB item, max 400 KB) small: the last turns only.
MAX_HISTORY_MESSAGES = 40


@dataclass
class TurnResult:
    reply: str
    tools_used: list[str]


def trim_history(messages: list) -> list:
    """The last MAX_HISTORY_MESSAGES messages, starting at a user message so no
    tool result is left without the model call that asked for it."""
    if len(messages) <= MAX_HISTORY_MESSAGES:
        return messages
    tail = messages[-MAX_HISTORY_MESSAGES:]
    for i, m in enumerate(tail):
        if isinstance(m, HumanMessage):
            return tail[i:]
    return tail[-1:]


def chat_turn(graph, store: Store, thread_id: str, message: str) -> TurnResult:
    history = messages_from_dict(store.repo.get_history(thread_id))
    before = len(history)
    result = graph.invoke(
        {"messages": [*history, HumanMessage(message)]},
        {"configurable": {"thread_id": thread_id}},
    )
    messages = result["messages"]
    new = messages[before + 1:]
    tools_used = [call["name"] for m in new for call in (getattr(m, "tool_calls", None) or [])]
    store.repo.put_history(thread_id, messages_to_dict(trim_history(messages)))
    return TurnResult(reply=text_of(messages[-1]), tools_used=tools_used)
