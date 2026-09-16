from __future__ import annotations

import operator
import os
import time
import uuid
from pathlib import Path
from typing import Annotated, Literal, TypedDict

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from langchain_core.messages import AIMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig, RunnableLambda
from langchain_core.tools import StructuredTool
from langfuse import get_client
from langfuse.langchain import CallbackHandler
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field


class AgentState(TypedDict):
    question: str
    scenario: str
    category: str
    context: str
    answer: str
    events: Annotated[list[dict], operator.add]


class ToolFailure(RuntimeError):
    def __init__(self, message: str, events: list[dict]):
        super().__init__(message)
        self.events = events


class RunRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    scenario: Literal["normal", "slow", "failure"] = "normal"


def event(node: str, label: str, started: float, status: str = "ok", detail: str = "") -> dict:
    return {
        "node": node,
        "label": label,
        "duration_ms": round((time.perf_counter() - started) * 1000, 1),
        "status": status,
        "detail": detail,
    }


# LangChain: Prompt + Runnable + parser for intent classification.
classification_prompt = ChatPromptTemplate.from_messages(
    [
        ("system", "把用户问题分类为 knowledge、order 或 weather，只输出分类名。"),
        ("human", "{question}"),
    ]
).with_config(run_name="classification-prompt")


def rule_based_classifier(prompt_value) -> AIMessage:
    text = str(prompt_value.messages[-1].content).lower()
    if any(word in text for word in ["订单", "退款", "物流", "快递"]):
        category = "order"
    elif any(word in text for word in ["天气", "温度", "下雨", "weather"]):
        category = "weather"
    else:
        category = "knowledge"
    time.sleep(0.10)
    return AIMessage(content=category)


classifier_chain = (
    classification_prompt
    | RunnableLambda(rule_based_classifier).with_config(run_name="deterministic-classifier-model")
    | StrOutputParser().with_config(run_name="classification-parser")
).with_config(run_name="langchain-classifier-chain")


# LangChain typed tools, selected by a LangGraph conditional edge.
def knowledge_search(question: str, scenario: str) -> str:
    """Search the internal technical knowledge base."""
    time.sleep(1.8 if scenario == "slow" else 0.20)
    if scenario == "failure":
        raise RuntimeError("知识库连接超时（Demo 主动制造的错误）")
    return "知识库：LangChain 提供模型、Prompt、Retriever 和 Tool 的统一接口。"


def order_query(question: str, scenario: str) -> str:
    """Query order delivery status."""
    time.sleep(1.8 if scenario == "slow" else 0.20)
    if scenario == "failure":
        raise RuntimeError("订单服务连接超时（Demo 主动制造的错误）")
    return "订单服务：演示订单已出库，预计明天下午送达。"


def weather_query(question: str, scenario: str) -> str:
    """Query current weather information."""
    time.sleep(1.8 if scenario == "slow" else 0.20)
    if scenario == "failure":
        raise RuntimeError("天气服务连接超时（Demo 主动制造的错误）")
    return "天气服务：演示城市今天 24°C，多云，降水概率 20%。"


knowledge_tool = StructuredTool.from_function(knowledge_search, name="knowledge_search")
order_tool = StructuredTool.from_function(order_query, name="order_query")
weather_tool = StructuredTool.from_function(weather_query, name="weather_query")


# LangChain answer prompt + model interface + output parser.
answer_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "你是企业 Agent Demo。根据工具结果准确回答，并用一句话说明使用了哪个业务路由。",
        ),
        (
            "human",
            "[scenario={scenario}]\n问题：{question}\n路由：{category}\n工具结果：{context}",
        ),
    ]
).with_config(run_name="answer-prompt")


def deterministic_chat_model(prompt_value) -> AIMessage:
    text = prompt_value.to_string()
    time.sleep(1.1 if "[scenario=slow]" in text else 0.28)
    human_part = text.split("Human:", 1)[-1].strip()
    clean = human_part.replace("[scenario=slow]", "").replace("[scenario=normal]", "").strip()
    return AIMessage(content="这是 LangChain 模型接口生成的可复现回答：\n" + clean)


answer_chain = (
    answer_prompt
    | RunnableLambda(deterministic_chat_model).with_config(run_name="deterministic-chat-model")
    | StrOutputParser().with_config(run_name="answer-parser")
).with_config(run_name="langchain-answer-chain")


def classify(state: AgentState, config: RunnableConfig) -> dict:
    started = time.perf_counter()
    category = classifier_chain.invoke({"question": state["question"]}, config=config).strip()
    return {
        "category": category,
        "events": [event("classify", "LangChain 意图分类", started, detail=f"route={category}")],
    }


def route_after_classification(state: AgentState) -> str:
    return state["category"]


def invoke_tool(state: AgentState, config: RunnableConfig, tool: StructuredTool, label: str) -> dict:
    started = time.perf_counter()
    try:
        context = tool.invoke(
            {"question": state["question"], "scenario": state["scenario"]},
            config=config,
        )
    except Exception as exc:
        failed = event("tool", label, started, status="error", detail=str(exc))
        raise ToolFailure(str(exc), state.get("events", []) + [failed]) from exc
    return {
        "context": context,
        "events": [event("tool", label, started, detail=context)],
    }


def knowledge_node(state: AgentState, config: RunnableConfig) -> dict:
    return invoke_tool(state, config, knowledge_tool, "LangChain 知识库工具")


def order_node(state: AgentState, config: RunnableConfig) -> dict:
    return invoke_tool(state, config, order_tool, "LangChain 订单工具")


def weather_node(state: AgentState, config: RunnableConfig) -> dict:
    return invoke_tool(state, config, weather_tool, "LangChain 天气工具")


def compose(state: AgentState, config: RunnableConfig) -> dict:
    started = time.perf_counter()
    answer = answer_chain.invoke(
        {
            "question": state["question"],
            "scenario": state["scenario"],
            "category": state["category"],
            "context": state["context"],
        },
        config=config,
    )
    return {
        "answer": answer,
        "events": [event("compose", "LangChain 回答链", started, detail="Prompt → Model → Parser")],
    }


def safety_check(state: AgentState) -> dict:
    started = time.perf_counter()
    time.sleep(0.08)
    return {
        "answer": state["answer"] + "\n\n安全检查：通过。",
        "events": [event("safety", "输出安全检查", started, detail="通过")],
    }


# LangGraph: shared state, conditional routing, transitions and failure propagation.
builder = StateGraph(AgentState)
builder.add_node("classify", classify)
builder.add_node("knowledge_tool", knowledge_node)
builder.add_node("order_tool", order_node)
builder.add_node("weather_tool", weather_node)
builder.add_node("compose", compose)
builder.add_node("safety", safety_check)
builder.add_edge(START, "classify")
builder.add_conditional_edges(
    "classify",
    route_after_classification,
    {"knowledge": "knowledge_tool", "order": "order_tool", "weather": "weather_tool"},
)
for tool_node in ["knowledge_tool", "order_tool", "weather_tool"]:
    builder.add_edge(tool_node, "compose")
builder.add_edge("compose", "safety")
builder.add_edge("safety", END)
graph = builder.compile()

app = FastAPI(title="LangChain + LangGraph + Langfuse 可观测 Demo")
index_path = Path(os.getenv("INDEX_HTML_PATH", Path(__file__).parent / "static/index.html"))
index_html = index_path.read_text(encoding="utf-8")
langfuse = get_client()


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return index_html


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok", "stack": ["langchain", "langgraph", "langfuse"]}


@app.post("/api/run")
def run_agent(request: RunRequest):
    request_id = str(uuid.uuid4())
    trace_id = langfuse.create_trace_id(seed=request_id)
    started = time.perf_counter()
    callback = CallbackHandler()
    events: list[dict] = []
    status = "ok"
    answer = ""
    error = ""

    with langfuse.start_as_current_observation(
        name="agent-demo-request",
        as_type="agent",
        trace_context={"trace_id": trace_id},
        input={"question": request.question, "scenario": request.scenario},
    ) as root_span:
        try:
            result = graph.invoke(
                {
                    "question": request.question,
                    "scenario": request.scenario,
                    "category": "",
                    "context": "",
                    "answer": "",
                    "events": [],
                },
                config={
                    "callbacks": [callback],
                    "run_name": "langchain-langgraph-observability-demo",
                    "tags": ["kubernetes-demo", request.scenario, "three-layer-stack"],
                    "metadata": {
                        "langfuse_user_id": "demo-user",
                        "langfuse_session_id": "kubernetes-live-demo",
                        "langfuse_tags": ["kubernetes-demo", request.scenario, "three-layer-stack"],
                        "request_id": request_id,
                        "scenario": request.scenario,
                    },
                },
            )
            events = result["events"]
            answer = result["answer"]
            root_span.update(output={"answer": answer, "events": events})
        except ToolFailure as exc:
            status = "error"
            error = str(exc)
            events = exc.events
            root_span.update(level="ERROR", status_message=error, output={"error": error})
        except Exception as exc:
            status = "error"
            error = f"{type(exc).__name__}: {exc}"
            root_span.update(level="ERROR", status_message=error, output={"error": error})
    langfuse.flush()

    project_id = os.getenv("LANGFUSE_PROJECT_ID", "langgraph-demo")
    public_url = os.getenv("LANGFUSE_PUBLIC_URL", "http://127.0.0.1:13000").rstrip("/")
    trace_url = (
        f"{public_url}/project/{project_id}/traces/{trace_id}"
        if trace_id
        else f"{public_url}/project/{project_id}/traces"
    )

    return JSONResponse(
        {
            "status": status,
            "request_id": request_id,
            "trace_id": trace_id,
            "trace_url": trace_url,
            "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            "events": events,
            "answer": answer,
            "error": error,
            "stack": {
                "langchain": "Prompt + StructuredTool + Runnable model + OutputParser",
                "langgraph": "StateGraph + conditional edges + shared state",
                "langfuse": "CallbackHandler + trace + observations + errors",
            },
        }
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080)
