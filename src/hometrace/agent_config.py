"""Explicit optional Agent configuration; no secret in repr or diagnostics."""

from dataclasses import dataclass, field
import os
from pathlib import Path
from urllib.parse import urlsplit


class AgentConfigError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class LLMConfig:
    provider: str
    model: str
    base_url: str
    timeout_seconds: int
    max_retries: int
    use_responses_api: bool


@dataclass(frozen=True)
class BudgetConfig:
    max_model_calls: int
    max_tool_calls: int
    max_viewpoints: int
    max_total_tokens: int
    show_tool_trace: bool


@dataclass(frozen=True)
class AgentConfig:
    llm: LLMConfig
    agent: BudgetConfig
    api_key: str = field(repr=False)
    project_root: Path
    config_path: Path


def disable_external_tracing():
    # Explicitly override inherited shell tracing switches before importing SDKs.
    for key in ("LANGCHAIN_TRACING", "LANGCHAIN_TRACING_V2", "LANGSMITH_TRACING",
                "LANGSMITH_TRACING_V2", "LANGSMITH_OTEL_ENABLED"):
        os.environ[key] = "false"
    for key in ("LANGCHAIN_API_KEY", "LANGSMITH_API_KEY"):
        os.environ.pop(key, None)


def load_agent_config(config_path=None, *, project_root=None) -> AgentConfig:
    try:
        import yaml
        from dotenv import load_dotenv
    except ImportError:
        raise AgentConfigError("DEPENDENCY_UNAVAILABLE", "Install HomeTrace [agent] dependencies") from None
    root = Path(project_root).resolve() if project_root else Path(__file__).resolve().parents[2]
    path = Path(config_path).resolve() if config_path else root / "config.yaml"
    try:
        document = path.read_text(encoding="utf-8-sig")
        if len(document) > 65536:
            raise AgentConfigError("CONFIG_INVALID", "Configuration exceeds size limit")
        value = yaml.safe_load(document)
        # safe_load is used for values, while the syntax tree rejects ambiguous duplicate keys.
        visited = set()
        def check_keys(node):
            if node is not None and id(node) in visited:
                raise AgentConfigError("CONFIG_INVALID", "Repeated YAML aliases are not accepted")
            visited.add(id(node))
            if isinstance(node,yaml.MappingNode):
                keys = [key.value for key,_ in node.value]
                if any(not isinstance(key,str) for key in keys) or len(set(keys)) != len(keys):
                    raise AgentConfigError("CONFIG_INVALID", "Duplicate or complex YAML key")
                for _,child in node.value:
                    check_keys(child)
            elif isinstance(node,yaml.SequenceNode):
                for child in node.value:
                    check_keys(child)
        check_keys(yaml.compose(document))
    except (OSError, UnicodeError, yaml.YAMLError, RecursionError):
        raise AgentConfigError("CONFIG_INVALID", "Cannot read a valid config.yaml") from None

    def require(condition, message):
        if not condition:
            raise AgentConfigError("CONFIG_INVALID", message)

    schema = {"llm": set(LLMConfig.__dataclass_fields__), "agent": set(BudgetConfig.__dataclass_fields__),
              "vision": {"backend"}, "privacy": {"send_raw_images_to_llm", "external_tracing_enabled"}}
    require(type(value) is dict and set(value) == set(schema), "Unexpected configuration sections")
    for section, keys in schema.items():
        require(type(value[section]) is dict and set(value[section]) == keys, f"Invalid {section} keys")
    llm, budget = value["llm"], value["agent"]
    require(llm["provider"] == "openai_compatible", "Unsupported provider")
    require(type(llm["model"]) is str and 1 <= len(llm["model"]) <= 120 and llm["model"].isascii()
            and not any(c.isspace() for c in llm["model"]), "Invalid model identifier")
    require(type(llm["base_url"]) is str, "Invalid base URL")
    try:
        url = urlsplit(llm["base_url"])
        valid = url.scheme == "https" and url.hostname and not (url.username or url.password or url.query or url.fragment)
        valid = valid and (url.port is None or 1 <= url.port <= 65535) and not any(c.isspace() for c in llm["base_url"])
    except ValueError:
        valid = False
    require(valid, "Base URL must be HTTPS without credentials, query or fragment")
    for key, low, high in (("timeout_seconds", 1, 120), ("max_retries", 0, 2)):
        require(type(llm[key]) is int and low <= llm[key] <= high, f"Invalid llm.{key}")
    require(llm["use_responses_api"] is False, "Chat Completions is required")
    for key, low, high in (("max_model_calls", 1, 20), ("max_tool_calls", 1, 40),
                           ("max_viewpoints", 1, 10), ("max_total_tokens", 256, 32000)):
        require(type(budget[key]) is int and low <= budget[key] <= high, f"Invalid agent.{key}")
    require(type(budget["show_tool_trace"]) is bool, "Invalid show_tool_trace")
    require(value["vision"]["backend"] == "orb", "Only the verified ORB backend is available")
    require(all(v is False for v in value["privacy"].values()), "Image upload and external tracing are disabled")
    load_dotenv(root / ".env", override=False)
    key = os.environ.get("HOMETRACE_LLM_API_KEY", "").strip()
    if not key:
        raise AgentConfigError("MODEL_UNAVAILABLE", "HOMETRACE_LLM_API_KEY is missing in local .env")
    disable_external_tracing()
    return AgentConfig(LLMConfig(**llm), BudgetConfig(**budget), key, root, path)
