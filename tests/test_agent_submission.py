import subprocess
import pytest
from hometrace.submission import collect_source,source_allowed,SubmissionError


def repo(tmp_path):
    subprocess.run(["git","init",str(tmp_path)],capture_output=True,check=True)
    (tmp_path/"README.md").write_text("sample")
    (tmp_path/"pyproject.toml").write_text("sample")
    (tmp_path/"src/hometrace").mkdir(parents=True)
    (tmp_path/"src/hometrace/__main__.py").write_text("pass")
    subprocess.run(["git","-C",str(tmp_path),"add","."],check=True,capture_output=True)
    subprocess.run(["git","-C",str(tmp_path),"-c","user.name=Test","-c","user.email=test@example.invalid","commit","-m","test"],check=True,capture_output=True)
    return tmp_path


def test_source_configuration_allowlist():
    assert source_allowed("config.yaml") and source_allowed(".env.example")
    for name in (".env",".env.local","local_data/.env","config.secret.yaml","model.pt","memory.sqlite3"):
        assert not source_allowed(name)


def test_empty_example_and_config_export_without_env(tmp_path):
    root=repo(tmp_path)
    (root/".env.example").write_text("HOMETRACE_LLM_API_KEY=\n")
    (root/".env").write_text("HOMETRACE_LLM_API_KEY=private-test-value")
    (root/"config.yaml").write_text("llm:\n  model: example\n")
    entries,_=collect_source(root)
    names=[e.name for e in entries]
    assert any(n.endswith("/.env.example") for n in names)
    assert any(n.endswith("/config.yaml") for n in names)
    assert not any(n.endswith("/.env") for n in names)


@pytest.mark.parametrize("name,content",[(".env.example","HOMETRACE_LLM_API_KEY=private-test-value"),("config.yaml","llm:\n  api_key: private-test-value\n")])
def test_populated_secret_input_rejected(tmp_path,name,content):
    root=repo(tmp_path);(root/name).write_text(content)
    with pytest.raises(SubmissionError):collect_source(root)


def test_local_key_copied_into_ordinary_source_is_rejected(tmp_path):
    root=repo(tmp_path)
    (root/".env").write_text("HOMETRACE_LLM_API_KEY=synthetic-private-value")
    (root/"README.md").write_text("accidental synthetic-private-value")
    with pytest.raises(SubmissionError,match="configured private API key"):
        collect_source(root)
