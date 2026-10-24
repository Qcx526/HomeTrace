"""The only runtime model path is a real configured Chat Completions API."""

from .agent_config import disable_external_tracing


def create_model(config):
    disable_external_tracing()
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(model=config.llm.model, base_url=config.llm.base_url,
                      api_key=config.api_key, timeout=config.llm.timeout_seconds,
                      max_retries=config.llm.max_retries, use_responses_api=False)


def safe_model_error(exc):
    """Never log provider bodies, headers, request text or exception messages."""
    name = type(exc).__name__
    status = getattr(exc, "status_code", None)
    return {"code": "MODEL_UNAVAILABLE", "error_type": name,
            "http_status": status if type(status) is int and 100 <= status <= 599 else None}


def response_metrics(message, elapsed_ms):
    meta = message.response_metadata or {}
    return {"latency_ms": round(elapsed_ms, 3), "usage": message.usage_metadata,
            "model": meta.get("model_name"), "finish_reason": meta.get("finish_reason"),
            "request_id": meta.get("request_id"), "response_id": message.id}
