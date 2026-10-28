"""Source delivery keeps legacy regression fixtures, not legacy runtime pages."""
from pathlib import Path

from hometrace.submission import source_allowed


def test_delivery_keeps_current_instructions_and_exact_legacy_fixtures():
    for name in ('DELIVERABLE_DEMO.md','HOUSEHOLD_PHOTO_FLOW.md','HOUSEHOLD_PHOTO_AGENT.md',
                 'REAL_PHOTO_CAPTURE_GUIDE.md','HISTORY_INDEX.md'):
        assert source_allowed('docs/'+name)
    for name in ('index.html','app.js','style.css','agent.html','agent.js','agent.css',
                 'household.html','household.js','household.css'):
        assert source_allowed('tests/fixtures/legacy_web/'+name)
    for name in ('unreviewed.html','secret.json','picture.png','database.sqlite3'):
        assert not source_allowed('tests/fixtures/legacy_web/'+name)
    assert not source_allowed('tests/fixtures/legacy_web/extra/index.html')
    assert not source_allowed('local_data/reference.jpg')


def test_current_runtime_assets_have_no_historical_demo_links():
    web=Path(__file__).resolve().parents[1]/'src/hometrace/web'
    assert {p.name for p in web.iterdir() if p.is_file()} == {'home-flow.html','home-flow.css','home-flow.js'}
    html=(web/'home-flow.html').read_text(encoding='utf-8')
    for link in ('/agent.html','/household.html','127.0.0.1:8786'):
        assert link not in html
