"""A synthetic official package must keep the current runnable Demo support files."""

import zipfile

from hometrace import submission as sub
from test_official_submission import official_bundle
from test_submission import bundle


def test_official_package_keeps_current_guides_and_legacy_browser_fixtures(bundle):
    root, _, _, path, _ = official_bundle(bundle)
    guides = (
        "OFFICIAL_SUBMISSION.md", "DELIVERABLE_DEMO.md", "HOUSEHOLD_WORKSPACE.md",
        "HOUSEHOLD_PHOTO_FLOW.md", "HOUSEHOLD_PHOTO_AGENT.md", "VISUAL_AGENT_LOOP.md",
        "REAL_CUP_AGENT_ACCEPTANCE.md", "VISUAL_AGENT_DECISION_REFINEMENT.md",
        "OWNER_MEMORY_RESTART_ACCEPTANCE.md", "WORKSPACE_LOCATIONS_AND_NEW_PHOTOS.md",
        "DELIVERY_CLOSEOUT_20261101.md",
    )
    expected = ["docs/" + name for name in guides]
    expected += ["tests/fixtures/legacy_web/" + name for name in sub.LEGACY_WEB_FIXTURES]
    for name in expected:
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("TEST_ONLY content for " + name, encoding="utf-8")
    excluded = ("docs/private-owner-review.json", "tests/fixtures/legacy_web/private.jpg",
                "tests/fixtures/legacy_web/owner.sqlite3")
    for name in excluded:
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("TEST_ONLY private placeholder", encoding="utf-8")

    report = sub.build(path, root)

    assert report["status"] == "TEST_ONLY_VERIFIED"
    with zipfile.ZipFile(root / "dist_submission/TEST_ONLY-candidate-HomeTrace.zip") as archive:
        assert archive.testzip() is None
        prefix = "04_核心源代码/"
        for name in expected:
            assert archive.read(prefix + name) == (root / name).read_bytes()
        assert all(prefix + name not in archive.namelist() for name in excluded)
