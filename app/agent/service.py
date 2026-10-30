from pydantic import TypeAdapter

from app.agent.graph import ConsultationEngine
from app.agent.model import OpenAIDecider
from app.consultation_contract import Topic
from app.rag.retrieval import PolicySearchResult
from app.schemas import OrderLookupResult
from app.tools.orders import lookup_order
from app.tools.policies import search_policy


def get_consultation_engine() -> ConsultationEngine:
    # One graph runtime; no AgentExecutor/create_agent nested inside it.
    def lookup(order_id: str) -> OrderLookupResult:
        return TypeAdapter(OrderLookupResult).validate_python(
            lookup_order.invoke({"order_id": order_id})
        )

    def search(query: str, topic: Topic | None) -> PolicySearchResult:
        return PolicySearchResult.model_validate(
            search_policy.invoke({"query": query, "topic": topic})
        )

    return ConsultationEngine(OpenAIDecider(), lookup, search)
