"""Regression test for a real bug: bootstrap.py, daily_report.py and change_proposals.py
each computed the repo root one directory short (parents[3] instead of parents[4]), so
they'd read/write learnings/changes/results under backend/ instead of the real tracked
directories. Every existing test for those modules monkeypatched the path away, so none of
them caught it — this test checks the *unpatched* default resolves correctly.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_repo_root_sanity():
    # specs/ is always committed — a reliable anchor for "this is really the repo root."
    assert (REPO_ROOT / "specs").is_dir()
    assert (REPO_ROOT / "backend").is_dir()


def test_bootstrap_models_dir_points_at_repo_root_results():
    import tradingbot.execution.bootstrap as bootstrap

    assert bootstrap.MODELS_DIR == REPO_ROOT / "results" / "models"
    assert "backend" not in bootstrap.MODELS_DIR.parts


def test_daily_report_learnings_dir_points_at_real_learnings_folder():
    import tradingbot.learning_engine.daily_report as daily_report

    assert daily_report.LEARNINGS_DIR == REPO_ROOT / "learnings"
    assert (daily_report.LEARNINGS_DIR / "README.md").exists()


def test_change_proposals_changes_dir_points_at_real_changes_folder():
    import tradingbot.learning_engine.change_proposals as change_proposals

    assert change_proposals.CHANGES_DIR == REPO_ROOT / "changes"
    assert (change_proposals.CHANGES_DIR / "README.md").exists()


def test_bootstrap_and_api_agree_on_models_dir():
    """The two independent computations of MODELS_DIR must resolve to the same directory
    — this exact mismatch (one right, one off-by-one) is why the bug went unnoticed."""
    import tradingbot.api.app as api_app
    import tradingbot.execution.bootstrap as bootstrap

    assert bootstrap.MODELS_DIR == api_app.MODELS_DIR
