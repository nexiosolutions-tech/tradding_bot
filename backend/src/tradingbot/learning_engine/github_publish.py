"""Publishes locally-generated learning/change files to GitHub via a dedicated branch +
PR — spec 09's fix for the 2026-08-15 finding that a Railway cron container's filesystem
is ephemeral and invisible to every other service (including the dashboard, which reads
learnings/ from its own, separate container). Pure REST calls (httpx) — no git/gh CLI
dependency, no assumption that `.git` exists in the deployed image.

Structural safety invariant: this module only ever calls the "create a new ref" endpoint
(POST /git/refs) to make a branch, and refuses outright if asked to target a protected
branch name — it has no code path capable of updating an existing ref, so it structurally
cannot push to main/master even if misconfigured. Same guarantee specs/09 already states
for the agentic loop ("o loop nunca escreve em main"), now also verified by test.
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from pathlib import Path

import httpx

GITHUB_API_BASE = "https://api.github.com"
PROTECTED_BRANCHES = ("main", "master")
DEFAULT_REPO = "nexiosolutions-tech/tradding_bot"

# backend/src/tradingbot/learning_engine/github_publish.py -> parents[4] is the repo root.
REPO_ROOT = Path(__file__).resolve().parents[4]


class PublishError(Exception):
    pass


@dataclass(frozen=True)
class PublishResult:
    branch: str
    pr_url: str


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def publish_files(
    repo: str,
    token: str,
    base_branch: str,
    new_branch: str,
    files: list[Path],
    commit_message: str,
    pr_title: str,
    pr_body: str,
    repo_root: Path = REPO_ROOT,
    client: httpx.Client | None = None,
) -> PublishResult:
    """Creates `new_branch` from the current tip of `base_branch`, commits every file in
    `files` onto it (one commit per file — the Contents API has no batch endpoint), and
    opens a PR back into `base_branch`. Raises PublishError before making any request if
    `new_branch` is a protected name — the one guardrail this module exists to enforce."""
    if new_branch in PROTECTED_BRANCHES:
        raise PublishError(f"refusing to publish to protected branch: {new_branch!r}")
    if not files:
        raise PublishError("no files to publish")

    owns_client = client is None
    client = client or httpx.Client(base_url=GITHUB_API_BASE, headers=_headers(token), timeout=15.0)
    try:
        base_ref = client.get(f"/repos/{repo}/git/ref/heads/{base_branch}")
        base_ref.raise_for_status()
        base_sha = base_ref.json()["object"]["sha"]

        create_ref = client.post(f"/repos/{repo}/git/refs", json={"ref": f"refs/heads/{new_branch}", "sha": base_sha})
        create_ref.raise_for_status()

        for file_path in files:
            repo_relative_path = file_path.relative_to(repo_root).as_posix()
            content_b64 = base64.b64encode(file_path.read_bytes()).decode("ascii")
            put_content = client.put(
                f"/repos/{repo}/contents/{repo_relative_path}",
                json={"message": commit_message, "content": content_b64, "branch": new_branch},
            )
            put_content.raise_for_status()

        create_pr = client.post(
            f"/repos/{repo}/pulls",
            json={"title": pr_title, "body": pr_body, "head": new_branch, "base": base_branch},
        )
        create_pr.raise_for_status()
        pr_url = create_pr.json()["html_url"]
    finally:
        if owns_client:
            client.close()

    return PublishResult(branch=new_branch, pr_url=pr_url)


def maybe_publish(
    files: list[Path],
    branch_suffix: str,
    commit_message: str,
    pr_title: str,
    pr_body: str,
) -> PublishResult | None:
    """Env-driven convenience wrapper for the scripts — returns None (no-op) when
    GITHUB_TOKEN isn't set, so this stays additive: running a script locally without the
    token configured behaves exactly as before (files land on disk only)."""
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        return None
    repo = os.environ.get("GITHUB_REPO", DEFAULT_REPO)
    base_branch = os.environ.get("GITHUB_BASE_BRANCH", "main")
    return publish_files(
        repo=repo,
        token=token,
        base_branch=base_branch,
        new_branch=f"learning-loop/{branch_suffix}",
        files=files,
        commit_message=commit_message,
        pr_title=pr_title,
        pr_body=pr_body,
    )
