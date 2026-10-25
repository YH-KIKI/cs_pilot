"""Offline dependency smoke checks. Never sends requests to an AI provider."""

import platform
import sqlite3
from importlib.metadata import version
from typing import TypedDict

import chromadb
from chromadb.config import Settings
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langgraph.graph import END, START, StateGraph

from app.tools.orders import lookup_order


class SmokeState(TypedDict):
    count: int


def main() -> None:
    for name in (
        "fastapi",
        "uvicorn",
        "pydantic",
        "langchain",
        "langgraph",
        "langchain-openai",
        "langchain-chroma",
        "chromadb",
        "openai",
    ):
        print(f"{name}={version(name)}")
    print(f"Python={platform.python_version()}, SQLite={sqlite3.sqlite_version}")

    graph = StateGraph(SmokeState)
    graph.add_node("increment", lambda state: {"count": state["count"] + 1})
    graph.add_edge(START, "increment")
    graph.add_edge("increment", END)
    assert graph.compile().invoke({"count": 0}) == {"count": 1}

    # Construction and schema binding only. No invoke/embed request, no real key needed.
    model = ChatOpenAI(
        model="gpt-6-luna",
        api_key="offline-environment-check",
        use_responses_api=True,
        max_retries=0,
    )
    assert model.bind_tools([lookup_order]) is not None
    assert (
        OpenAIEmbeddings(model="text-embedding-3-small", api_key="offline-environment-check")
        is not None
    )

    client = chromadb.EphemeralClient(Settings(anonymized_telemetry=False))
    collection = client.create_collection("environment-smoke", embedding_function=None)
    collection.add(ids=["example"], embeddings=[[1.0, 0.0, 0.0]], documents=["offline"])
    assert collection.query(query_embeddings=[[1.0, 0.0, 0.0]], n_results=1)["ids"] == [["example"]]
    client.delete_collection("environment-smoke")
    print("LangGraph execution / OpenAI schema binding / Chroma search: OK (no AI API calls)")


if __name__ == "__main__":
    main()
