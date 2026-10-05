"""Streamlit chat UI:  streamlit run app.py"""

import uuid

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from anycart.graph import build_graph, text_of  # noqa: E402
from anycart.tools import STORE  # noqa: E402

st.set_page_config(page_title="AnyCart assistant", page_icon="🛒")
st.title("🛒 AnyCart shopping assistant")
st.caption("LangGraph agent on Amazon Bedrock. Demo store, nothing is really charged.")


def md(text: str) -> str:
    """Escape $ so Streamlit doesn't render prices as LaTeX maths."""
    return text.replace("$", r"\$")


@st.cache_resource
def get_app():
    return build_graph()


if "thread_id" not in st.session_state:
    st.session_state.thread_id = str(uuid.uuid4())
    st.session_state.history = []

config = {"configurable": {"thread_id": st.session_state.thread_id}}

with st.sidebar:
    st.subheader("Your cart")
    cart = STORE.summary(st.session_state.thread_id)
    for line in cart["items"]:
        st.markdown(md(f"{line['qty']} × {line['name']} — A${line['line_total']:.2f}"))
    st.markdown(md(f"**Total: A${cart['total']:.2f}** (shipping A${cart['shipping']:.2f})"))
    if st.button("New conversation"):
        del st.session_state["thread_id"]
        st.rerun()

for role, text in st.session_state.history:
    st.chat_message(role).markdown(md(text))

if prompt := st.chat_input("Try: find earbuds under $100"):
    st.chat_message("user").markdown(md(prompt))
    try:
        with st.spinner("Thinking..."):
            result = get_app().invoke({"messages": [("user", prompt)]}, config)
    except Exception as err:  # most often missing AWS credentials or model access
        st.error(f"Couldn't reach the model on Bedrock: {err}\n\nCheck AWS credentials, AWS_REGION and BEDROCK_MODEL_ID (README steps 2-3).")
        st.stop()
    answer = text_of(result["messages"][-1])
    st.chat_message("assistant").markdown(md(answer))
    st.session_state.history += [("user", prompt), ("assistant", answer)]
    st.rerun()
