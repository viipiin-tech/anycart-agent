# AnyCart: shopping-assistant agent (LangGraph + Amazon Bedrock, FastAPI on AWS Lambda)

A chat assistant for a demo online store. It searches products, manages a cart, places orders and checks order status by calling tools. The agent loop is built with **LangGraph**, the model is **Claude on Amazon Bedrock** (Converse API through `langchain-aws`), and it is served as a **FastAPI** API that runs locally or on **AWS Lambda** behind **API Gateway**, with state in **DynamoDB**.

```
client ──HTTPS──► API Gateway (HTTP API, throttled)
                        │
                        ▼
              AWS Lambda: FastAPI + Mangum ──────────► DynamoDB (single table):
                        │                               carts, orders, stock, chat history
                        ▼
              LangGraph agent
              START → agent ─(tool?)→ tools → agent … → END
                        │
                        ▼
              Amazon Bedrock: Claude (IAM allows one model only)
```

| Path | What it is |
|---|---|
| `src/anycart/graph.py` | The graph: an LLM node, a `ToolNode` and a conditional edge. A checkpointer keeps memory for the CLI/Streamlit; the API runs it stateless. |
| `src/anycart/tools.py` | 6 tools: `search_products`, `add_to_cart`, `remove_from_cart`, `view_cart`, `checkout`, `order_status` |
| `src/anycart/store.py` | The shop's rules: search, stock limits, shipping, checkout (12 demo products, prices in AUD) |
| `src/anycart/repository.py` | Storage: `MemoryRepository` (local, tests) and `DynamoRepository` (Lambda) behind one interface |
| `src/anycart/service.py` | One API chat turn: load history, run the agent, save history |
| `src/anycart/api.py` | FastAPI app: Pydantic request/response models, API-key check, JSON logs |
| `src/anycart/handler.py` | Lambda entry point (Mangum adapter) |
| `template.yaml` | AWS SAM: DynamoDB table, Lambda, HTTP API, least-privilege IAM, log group |
| `app.py` · `cli.py` | Streamlit chat UI · terminal chat (local, in memory) |
| `tests/` | 16 offline tests: store, the full graph and the API with a scripted fake model, DynamoDB via moto, the Lambda handler with an API Gateway event |

## 1. Run it locally (no AWS needed for the tests)
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pytest -q                     # 16 tests, no cloud account needed
cfn-lint template.yaml        # checks the SAM template
```

## 2. Set up Amazon Bedrock
1. In the AWS console choose a region with Claude on Bedrock, such as `ap-southeast-2` (Sydney).
2. **Bedrock → Model catalog**: open a Claude model; complete the first-use form if asked.
3. Note two IDs: the **inference profile ID** you will call (for example one starting `au.` or `apac.`) and the **foundation model ID** (the same without that prefix). The IAM policy in `template.yaml` uses both.
4. For local runs: `aws configure` with a user that can call that model, then `cp .env.example .env` and set `AWS_REGION` and `BEDROCK_MODEL_ID`.

## 3. Chat locally
```bash
python cli.py                                     # terminal
streamlit run app.py                              # browser UI at http://localhost:8501
PYTHONPATH=src uvicorn anycart.api:app --reload   # the API, docs at http://localhost:8000/docs
```

## 4. Deploy to AWS Lambda (AWS SAM)
Needs the [AWS SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html).
```bash
sam build
sam deploy --guided      # stack name, region, BedrockModelId, FoundationModelId, ApiKey
```
`sam deploy --guided` saves your answers in `samconfig.toml`, which is git-ignored because it can hold the API key. The output `ApiUrl` is your endpoint:
```bash
curl -s "$API_URL/health"
curl -s -X POST "$API_URL/chat" -H "content-type: application/json" -H "x-api-key: $API_KEY" \
     -d '{"message": "find earbuds under $100"}'
# send the returned thread_id with the next message to continue the conversation
```
Remove everything with `sam delete`.

## API
| Method | Path | Body / result |
|---|---|---|
| `POST` | `/chat` | `{"message": "...", "thread_id": "optional"}` → `thread_id`, `reply`, `tools_used`, `cart`, `latency_ms` |
| `GET` | `/cart/{thread_id}` | items, subtotal, shipping, total |
| `GET` | `/orders/{order_id}` | status, total, items (`ORD-0901` and `ORD-0902` are samples) |
| `GET` | `/health` | `{"status": "ok", "storage": "dynamodb"}` (no key needed) |

Interactive docs: `/docs` (Swagger UI) and `/openapi.json`.

## How it works (interview talking points)
- **Agent loop**: `MessagesState` holds the conversation; `tools_condition` routes to the `ToolNode` when the model asks for a tool and ends the turn otherwise.
- **Tools and guardrails in code**: tools are plain Python functions with `@tool`; docstrings and type hints become the schema the model sees. The cart ID comes from `RunnableConfig`, so the model can't read or spoof another shopper's cart. Stock, price and shipping rules live in `store.py`, not in the prompt.
- **Stateless Lambda**: a Lambda's memory doesn't survive between invocations, so the API compiles the graph without a checkpointer and stores the history in DynamoDB, trimmed to the last 40 messages and starting at a user message so no tool result is orphaned.
- **Single-table DynamoDB**: carts, chat history, orders, stock and an order counter share one table keyed by `pk`/`sk`. Carts and chats expire after 7 days (TTL).
- **Atomic checkout**: one `TransactWriteItems` call decrements every line's stock (with a condition that stock never goes below zero), writes the order and deletes the cart. If any line is short, nothing changes.
- **Least-privilege IAM**: the Lambda role can do CRUD on its own table only, and `bedrock:InvokeModel` on one inference profile and its one foundation model. No keys are stored; the function uses its execution role.
- **Cost and abuse controls**: API Gateway throttling (5 requests/s, burst 10), an optional `x-api-key` check (constant-time compare), a 30 s timeout and a 2,000-character message limit. Set an AWS Budget alert too.
- **Errors and logs**: a model or AWS failure returns a 502 without internal details; each request logs one JSON line (thread, latency, tools used), easy to query in CloudWatch Logs Insights.
- **Testability**: `build_graph(llm=...)` accepts any chat model, and the API takes its agent and store through FastAPI dependencies, so the tests swap in a scripted fake model and moto's mock DynamoDB. GitHub Actions runs the tests and `cfn-lint` on every push.

## Next ideas
1. **Human-in-the-loop checkout**: LangGraph `interrupt()` so the graph pauses for an explicit "yes" before `checkout` runs.
2. **Product knowledge base**: a Bedrock Knowledge Base (RAG) over product manuals and an `ask_product_question` tool.
3. **Bedrock Guardrails**: attach a guardrail (PII and denied topics) to the model call.
4. **Auth**: replace the shared API key with Amazon Cognito (JWT authorizer on the HTTP API).
5. **Tracing**: AWS X-Ray or LangSmith traces for tool latency.

## Cost and safety
- Every chat turn is a paid Bedrock call. Set an AWS Budget alert, such as A$10/month; DynamoDB on-demand and Lambda cost cents at demo volumes.
- Never commit `.env`, `samconfig.toml` or AWS keys; `.gitignore` excludes them.
- This is a demo store: no real payments or personal data.
