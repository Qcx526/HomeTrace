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
    assert source_allowed("config.yaml") and source_allowed("config.photo-demo.yaml") and source_allowed(".env.example")
    for name in (".env",".env.local","local_data/.env","config.secret.yaml","config.photo-demo.private.yaml","model.pt","memory.sqlite3"):
        assert not source_allowed(name)


def test_empty_example_and_config_export_without_env(tmp_path):
    root=repo(tmp_path)
    (root/".env.example").write_text("HOMETRACE_LLM_API_KEY=\n")
    (root/".env").write_text("HOMETRACE_LLM_API_KEY=private-test-value")
    (root/"config.yaml").write_text("llm:\n  model: example\n")
    (root/"config.photo-demo.yaml").write_text("agent:\n  max_total_tokens: 32000\n")
    entries,_=collect_source(root)
    names=[e.name for e in entries]
    assert any(n.endswith("/.env.example") for n in names)
    assert any(n.endswith("/config.yaml") for n in names)
    assert any(n.endswith("/config.photo-demo.yaml") for n in names)
    assert not any(n.endswith("/.env") for n in names)


@pytest.mark.parametrize("name,content",[(".env.example","HOMETRACE_LLM_API_KEY=private-test-value"),("config.yaml","llm:\n  api_key: private-test-value\n"),("config.photo-demo.yaml","llm:\n  api_key: private-test-value\n")])
def test_populated_secret_input_rejected(tmp_path,name,content):
    root=repo(tmp_path);(root/name).write_text(content)
    with pytest.raises(SubmissionError):collect_source(root)


def test_local_key_copied_into_ordinary_source_is_rejected(tmp_path):
    root=repo(tmp_path)
    (root/".env").write_text("HOMETRACE_LLM_API_KEY=synthetic-private-value")
    (root/"README.md").write_text("accidental synthetic-private-value")
    with pytest.raises(SubmissionError,match="configured private API key"):
        collect_source(root)


def test_fresh_workflow_evidence_allowlist_is_exact(tmp_path):
    root=repo(tmp_path)
    included = (
        "docs/REAL_CUP_WORKFLOW_20261102.md",
        "docs/REAL_CUP_FRESH_WORKFLOW_20261102.md",
        "docs/DELIVERY_CLOSEOUT_20261102.md",
        "docs/evidence/issue-46/workflow.json",
        "docs/evidence/issue-46-new-photos/audit.json",
    )
    excluded = (
        "docs/evidence/issue-46-new-photos/private.json",
        "docs/evidence/issue-46-new-photos/scene.jpg",
        "docs/evidence/issue-46-new-photos/memory.sqlite3",
        "docs/evidence/private/workflow.json",
        "local_data/docs/evidence/issue-46/workflow.json",
    )
    for name in included + excluded:
        path=root/name;path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text("Synthetic TEST_ONLY source-policy fixture",encoding="utf-8")
    entries,_=collect_source(root)
    names={e.name.removeprefix("04_核心源代码/") for e in entries}
    assert set(included) <= names
    assert not set(excluded) & names


def test_photo_demo_config_cannot_export_configured_private_key(tmp_path,monkeypatch):
    root=repo(tmp_path)
    fake="TEST_ONLY_PHOTO_CONFIG_SECRET_9182"
    monkeypatch.setenv("HOMETRACE_LLM_API_KEY",fake)
    (root/"config.photo-demo.yaml").write_text("# "+fake,encoding="utf-8")
    with pytest.raises(SubmissionError,match="configured private API key"):
        collect_source(root)


def test_delivery_deck_generator_is_explicitly_exported_and_secret_checked(tmp_path):
    root=repo(tmp_path)
    path=root/'tools/create_delivery_deck.mjs'
    path.parent.mkdir()
    path.write_text('// Synthetic TEST_ONLY generator source',encoding='utf-8')
    assert source_allowed('tools/create_delivery_deck.mjs')
    assert not source_allowed('tools/unreviewed-private.mjs')
    entries,_=collect_source(root)
    assert any(e.name.endswith('/tools/create_delivery_deck.mjs') for e in entries)
    path.write_text('// ghp_'+'A'*40,encoding='utf-8')
    with pytest.raises(SubmissionError,match='credential'):
        collect_source(root)
