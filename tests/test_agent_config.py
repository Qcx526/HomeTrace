"""Offline configuration checks; synthetic credentials and model stubs only."""

import builtins
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

yaml = pytest.importorskip("yaml")
pytest.importorskip("dotenv")

from hometrace.agent_config import AgentConfigError, load_agent_config
from hometrace.agent_model import create_model, safe_model_error


SECRET = "synthetic-unit-test-secret"
TRACING_KEYS = (
    "LANGCHAIN_TRACING", "LANGCHAIN_TRACING_V2", "LANGSMITH_TRACING",
    "LANGSMITH_TRACING_V2", "LANGSMITH_OTEL_ENABLED",
)


@pytest.fixture
def configuration(tmp_path, monkeypatch):
    # Never inspect the developer's real .env or send a request to any model.
    monkeypatch.setenv("HOMETRACE_LLM_API_KEY", SECRET)
    for name in TRACING_KEYS:
        monkeypatch.setenv(name, "true")
    for name in ("LANGCHAIN_API_KEY", "LANGSMITH_API_KEY"):
        monkeypatch.setenv(name, "synthetic-tracing-key")
    value = {
        "llm": {
            "provider": "openai_compatible", "model": "test-model",
            "base_url": "https://example.invalid/compatible-mode/v1",
            "timeout_seconds": 60, "max_retries": 1, "use_responses_api": False,
        },
        "agent": {
            "max_model_calls": 8, "max_tool_calls": 12, "max_viewpoints": 5,
            "max_total_tokens": 12000, "show_tool_trace": True,
        },
        "vision": {"backend": "orb"},
        "privacy": {"send_raw_images_to_llm": False, "external_tracing_enabled": False},
    }
    path = tmp_path / "config.yaml"

    def write(updated=None):
        path.write_text(yaml.safe_dump(value if updated is None else updated), encoding="utf-8")
        return path

    write()
    return tmp_path, value, write


def test_valid_config_and_secret_repr(configuration):
    root, _, _ = configuration
    config = load_agent_config(project_root=root)
    assert config.api_key == SECRET
    assert SECRET not in repr(config)
    assert SECRET not in str(config)
    assert config.project_root == root.resolve()
    assert config.llm.use_responses_api is False
    assert config.agent.max_viewpoints == 5
    assert all(os.environ[name] == "false" for name in TRACING_KEYS)
    assert "LANGCHAIN_API_KEY" not in os.environ
    assert "LANGSMITH_API_KEY" not in os.environ


def test_duplicate_yaml_keys_are_rejected(configuration):
    root,_,write=configuration
    path=write()
    path.write_text(path.read_text()+"\nvision: {backend: orb}\n",encoding="utf-8")
    with pytest.raises(AgentConfigError) as error:
        load_agent_config(project_root=root)
    assert error.value.code=="CONFIG_INVALID"


def test_recursive_alias_is_explicit_config_failure(configuration):
    root,_,write=configuration
    write().write_text("llm: &loop {again: *loop}",encoding="utf-8")
    with pytest.raises(AgentConfigError):
        load_agent_config(project_root=root)


def test_environment_key_has_priority_over_local_dotenv(configuration):
    root, _, _ = configuration
    (root / ".env").write_text("HOMETRACE_LLM_API_KEY=synthetic-file-key\n", encoding="utf-8")
    assert load_agent_config(project_root=root).api_key == SECRET


def test_local_dotenv_key_loaded_when_environment_unset(configuration, monkeypatch):
    root, _, _ = configuration
    monkeypatch.delenv("HOMETRACE_LLM_API_KEY")
    (root / ".env").write_text("HOMETRACE_LLM_API_KEY=synthetic-file-key\n", encoding="utf-8")
    assert load_agent_config(project_root=root).api_key == "synthetic-file-key"


@pytest.mark.parametrize("value", [None, "", " \t "])
def test_missing_key_reports_model_unavailable(configuration, monkeypatch, value):
    root, _, _ = configuration
    if value is None:
        monkeypatch.delenv("HOMETRACE_LLM_API_KEY")
    else:
        monkeypatch.setenv("HOMETRACE_LLM_API_KEY", value)
    with pytest.raises(AgentConfigError) as error:
        load_agent_config(project_root=root)
    assert error.value.code == "MODEL_UNAVAILABLE"
    assert SECRET not in str(error.value)


@pytest.mark.parametrize("text", [
    "llm: [unterminated", "null", "[]", "true", "llm: {}",
    "!!python/object/apply:os.system ['echo must-not-execute']",
])
def test_invalid_or_unsafe_yaml_is_rejected(configuration, text):
    root, _, _ = configuration
    (root / "config.yaml").write_text(text, encoding="utf-8")
    with pytest.raises(AgentConfigError) as error:
        load_agent_config(project_root=root)
    assert error.value.code == "CONFIG_INVALID"
    assert text not in str(error.value)


@pytest.mark.parametrize("section,key,value", [
    ("llm", "provider", "offline"),
    ("llm", "model", ""),
    ("llm", "model", "a" * 121),
    ("llm", "model", "white space"),
    ("llm", "model", "模型"),
    ("llm", "model", 1),
    ("llm", "timeout_seconds", True),
    ("llm", "timeout_seconds", 0),
    ("llm", "timeout_seconds", 121),
    ("llm", "max_retries", -1),
    ("llm", "max_retries", 3),
    ("llm", "max_retries", "1"),
    ("llm", "use_responses_api", True),
    ("llm", "use_responses_api", 0),
    ("agent", "max_model_calls", 0),
    ("agent", "max_model_calls", 21),
    ("agent", "max_tool_calls", 41),
    ("agent", "max_tool_calls", 1.0),
    ("agent", "max_viewpoints", 11),
    ("agent", "max_viewpoints", False),
    ("agent", "max_total_tokens", 255),
    ("agent", "max_total_tokens", 32001),
    ("agent", "show_tool_trace", "true"),
    ("vision", "backend", "yoloe"),
    ("privacy", "send_raw_images_to_llm", True),
    ("privacy", "external_tracing_enabled", True),
    ("privacy", "external_tracing_enabled", 0),
])
def test_schema_types_and_bounds(configuration, section, key, value):
    root, data, write = configuration
    data[section][key] = value
    write()
    with pytest.raises(AgentConfigError) as error:
        load_agent_config(project_root=root)
    assert error.value.code == "CONFIG_INVALID"
    assert SECRET not in str(error.value)


@pytest.mark.parametrize("base_url", [
    None, "http://example.invalid/v1", "https:///v1",
    "https://user:password@example.invalid/v1", "https://user@example.invalid/v1",
    "https://example.invalid/v1?token=private", "https://example.invalid/v1#private",
    "https://example.invalid:0/v1", "https://example.invalid:65536/v1",
    "https://example.invalid:bad/v1", "https://[broken/v1",
    "https://example.invalid/white space",
])
def test_invalid_base_url(configuration, base_url):
    root, data, write = configuration
    data["llm"]["base_url"] = base_url
    write()
    with pytest.raises(AgentConfigError) as error:
        load_agent_config(project_root=root)
    assert error.value.code == "CONFIG_INVALID"
    assert "password" not in str(error.value)
    assert "token=private" not in str(error.value)


@pytest.mark.parametrize("mutation", ["section", "secret", "missing", "section_type"])
def test_unknown_missing_keys_and_yaml_secrets_rejected(configuration, mutation):
    root, data, write = configuration
    if mutation == "section":
        data["unexpected"] = {}
    elif mutation == "secret":
        data["llm"]["api_key"] = SECRET
    elif mutation == "missing":
        del data["agent"]["max_model_calls"]
    else:
        data["agent"] = []
    write()
    with pytest.raises(AgentConfigError) as error:
        load_agent_config(project_root=root)
    assert error.value.code == "CONFIG_INVALID"
    assert SECRET not in str(error.value)


def test_unreadable_config(configuration):
    root, _, _ = configuration
    with pytest.raises(AgentConfigError) as error:
        load_agent_config(root / "missing.yaml", project_root=root)
    assert error.value.code == "CONFIG_INVALID"


def test_explicit_config_path_and_bom(configuration):
    root, data, _ = configuration
    custom = root / "custom.yaml"
    custom.write_text(yaml.safe_dump(data), encoding="utf-8-sig")
    assert load_agent_config(custom, project_root=root).config_path == custom


def test_optional_imports_are_deferred_and_missing_dependency_reported(configuration, monkeypatch):
    root, _, _ = configuration
    program = """
import builtins
original_import = builtins.__import__
def block_optional(name, *args, **kwargs):
    if name.split('.')[0] in {'yaml', 'dotenv', 'langchain_openai', 'langgraph'}:
        raise ImportError('synthetic missing dependency')
    return original_import(name, *args, **kwargs)
builtins.__import__ = block_optional
import hometrace.agent_config
import hometrace.agent_model
print('optional imports deferred')
"""
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
    result = subprocess.run([sys.executable, "-c", program], capture_output=True, text=True, env=env, check=True)
    assert result.stdout.strip() == "optional imports deferred"
    normal_import = builtins.__import__

    def no_optional_import(name, *args, **kwargs):
        if name.split(".")[0] in {"yaml", "dotenv", "langchain_openai", "langgraph"}:
            raise ImportError("synthetic missing dependency")
        return normal_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_optional_import)
    with pytest.raises(AgentConfigError) as error:
        load_agent_config(project_root=root)
    assert error.value.code == "DEPENDENCY_UNAVAILABLE"


def test_model_factory_uses_chat_completions_and_disables_tracing(configuration, monkeypatch):
    root, _, _ = configuration
    config = load_agent_config(project_root=root)
    for name in TRACING_KEYS:
        monkeypatch.setenv(name, "true")
    calls = []

    def fake_chat_model(**kwargs):
        calls.append(kwargs)
        assert all(os.environ[name] == "false" for name in TRACING_KEYS)
        return object()

    monkeypatch.setitem(sys.modules, "langchain_openai", SimpleNamespace(ChatOpenAI=fake_chat_model))
    create_model(config)
    assert calls == [{
        "model": "test-model", "base_url": "https://example.invalid/compatible-mode/v1",
        "api_key": SECRET, "timeout": 60, "max_retries": 1, "use_responses_api": False,
    }]


def test_error_reporting_excludes_provider_body_and_secret():
    class SyntheticProviderError(Exception):
        status_code = 401

    exc = SyntheticProviderError(f"Authorization: Bearer {SECRET}; private request text")
    exc.body = {"secret": SECRET}
    report = safe_model_error(exc)
    assert report == {"code": "MODEL_UNAVAILABLE", "error_type": "SyntheticProviderError", "http_status": 401}
    assert SECRET not in repr(report)
    assert "private request text" not in repr(report)
