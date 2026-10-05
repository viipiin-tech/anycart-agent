# AnyCart: shopping-assistant agent (LangGraph + Amazon Bedrock)

A chat assistant for a demo online store. It searches products, manages a cart, places orders and checks order status by calling tools. The agent loop is built with **LangGraph**, and the model is **Claude on Amazon Bedrock** (Converse API through `langchain-aws`).

```
START → agent ──(wants a tool?)──► tools ──► agent … ──► END
```

- `anycart/graph.py`: the graph: an LLM node, a `ToolNode`, a conditional edge, and a checkpointer that keeps each conversation's memory by `thread_id`
- `anycart/tools.py`: 6 tools: `search_products`, `add_to_cart`, `remove_from_cart`, `view_cart`, `checkout`, `order_status`
- `anycart/store.py`: an in-memory catalogue, carts and orders (12 demo products in `anycart/data/products.json`, prices in AUD)
- `app.py`: Streamlit chat UI with a live cart sidebar · `cli.py`: terminal chat
- `tests/`: offline tests, including a full graph run with a scripted fake model (no AWS needed)

## Step by step

### 1. Get the code running (no AWS yet)
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest -q          # 4 tests pass without any cloud account
```

### 2. Set up Amazon Bedrock
1. Sign in to the AWS console. Choose a region that offers Claude on Bedrock, such as `ap-southeast-2` (Sydney) or `us-east-1`.
2. **Bedrock → Model catalog**: open a Claude model. If AWS asks for first-time access or a use-case form, complete it.
3. Copy the model's **model ID** or **inference profile ID** (some regions only allow calls through an inference profile).
4. **IAM**: give your user or role `bedrock:InvokeModel` and `bedrock:InvokeModelWithResponseStream`. The managed policy `AmazonBedrockLimitedAccess` also works while you are learning.
5. Run `aws configure` with that user's keys, or put the keys in `.env`.

### 3. Configure
```bash
cp .env.example .env   # set AWS_REGION and BEDROCK_MODEL_ID
```

### 4. Chat
```bash
python cli.py          # terminal
streamlit run app.py   # browser UI at http://localhost:8501
```
Try: *"find earbuds under $100"*, *"add two yoga mats"*, *"what's in my cart?"*, *"check out"*, *"where is order ORD-0901?"*.

## How it works (interview talking points)
- **State**: `MessagesState` holds the conversation. `InMemorySaver` checkpoints it per `thread_id`, so each chat has its own memory and its own cart.
- **Tools**: plain Python functions with `@tool`. Docstrings and type hints become the tool schema the model sees. The cart ID is injected through `RunnableConfig`, so the model can't reach another shopper's cart.
- **Routing**: `tools_condition` sends the turn to the `ToolNode` when the model asks for a tool, and ends it otherwise.
- **Guardrails in the prompt**: the agent never invents products or prices, and it confirms the total before `checkout`. Stock and price checks are enforced in code (`store.py`), not left to the model.
- **Testability**: `build_graph(llm=...)` accepts any chat model, so the tests swap in a scripted fake.

## Make it yours (do these before it goes on your resume)
1. **Human-in-the-loop checkout**: use LangGraph `interrupt()` so the graph pauses for an explicit "yes" before `checkout` runs.
2. **DynamoDB**: replace `store.py` with DynamoDB tables (products, carts, orders) and use a persistent checkpointer.
3. **Product knowledge base**: add a Bedrock Knowledge Base (RAG) over product manuals and a `ask_product_question` tool.
4. **Bedrock Guardrails**: attach a guardrail (PII and denied topics) to the model call.
5. **Observability**: trace runs with LangSmith or CloudWatch and log tool latency.
6. **Deploy**: put it in a container on AWS App Runner or ECS, or run it on Replit for a quick public demo. Streamlit needs a running Python server, so Netlify (static hosting) can host a landing page but not the app itself.

## Cost and safety
- Every chat turn is a paid Bedrock call. Set an AWS Budget alert, such as A$10/month.
- Never commit `.env` or AWS keys. `.gitignore` already excludes `.env`.
- This is a demo store: no real payments or personal data.
