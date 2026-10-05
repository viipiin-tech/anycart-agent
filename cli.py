"""Chat with AnyCart in the terminal:  python cli.py"""

import uuid

from dotenv import load_dotenv

load_dotenv()

from anycart.graph import build_graph, text_of  # noqa: E402


def main() -> None:
    app = build_graph()
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    print("AnyCart assistant. Type 'quit' to exit.")
    while (text := input("\nYou: ").strip()).lower() not in {"quit", "exit"}:
        if not text:
            continue
        result = app.invoke({"messages": [("user", text)]}, config)
        print(f"\nAnyCart: {text_of(result['messages'][-1])}")


if __name__ == "__main__":
    main()
