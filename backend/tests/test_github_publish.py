"""Unit tests for learning_engine/github_publish.py (spec 09) — no real network. The most
important test here is that publish_files refuses a protected branch name *before* making
any HTTP call at all, since that's the structural guarantee the module exists to provide.
"""

from __future__ import annotations

import json

import httpx
import pytest

from tradingbot.learning_engine import github_publish
from tradingbot.learning_engine.github_publish import PublishError, maybe_publish, publish_files


def _mock_transport(calls: list):
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path, request.content))
        if request.method == "GET" and request.url.path.endswith("/git/ref/heads/main"):
            return httpx.Response(200, json={"object": {"sha": "base-sha-123"}})
        if request.method == "POST" and request.url.path.endswith("/git/refs"):
            return httpx.Response(201, json={"ref": "refs/heads/learning-loop/2026-08-15"})
        if request.method == "PUT" and "/contents/" in request.url.path:
            return httpx.Response(201, json={"content": {"sha": "file-sha"}})
        if request.method == "POST" and request.url.path.endswith("/pulls"):
            return httpx.Response(201, json={"html_url": "https://github.com/org/repo/pull/1"})
        raise AssertionError(f"unexpected request: {request.method} {request.url.path}")

    return httpx.MockTransport(handler)


def test_publish_files_happy_path(tmp_path):
    file_path = tmp_path / "learnings" / "2026-08-15.md"
    file_path.parent.mkdir()
    file_path.write_text("# Learnings\n")

    calls: list = []
    client = httpx.Client(base_url=github_publish.GITHUB_API_BASE, transport=_mock_transport(calls))

    result = publish_files(
        repo="org/repo",
        token="fake-token",
        base_branch="main",
        new_branch="learning-loop/2026-08-15",
        files=[file_path],
        commit_message="learnings 2026-08-15",
        pr_title="Learnings 2026-08-15",
        pr_body="auto-generated",
        repo_root=tmp_path,
        client=client,
    )

    assert result.branch == "learning-loop/2026-08-15"
    assert result.pr_url == "https://github.com/org/repo/pull/1"
    methods = [c[0] for c in calls]
    assert methods == ["GET", "POST", "PUT", "POST"]


def test_publish_files_sends_correct_repo_relative_path(tmp_path):
    file_path = tmp_path / "changes" / "2026-08-15-something.md"
    file_path.parent.mkdir()
    file_path.write_text("proposal")

    calls: list = []
    client = httpx.Client(base_url=github_publish.GITHUB_API_BASE, transport=_mock_transport(calls))

    publish_files(
        repo="org/repo",
        token="fake-token",
        base_branch="main",
        new_branch="learning-loop/2026-08-15",
        files=[file_path],
        commit_message="msg",
        pr_title="title",
        pr_body="body",
        repo_root=tmp_path,
        client=client,
    )

    put_call = next(c for c in calls if c[0] == "PUT")
    assert put_call[1] == "/repos/org/repo/contents/changes/2026-08-15-something.md"
    body = json.loads(put_call[2])
    assert body["branch"] == "learning-loop/2026-08-15"


@pytest.mark.parametrize("protected", ["main", "master"])
def test_publish_files_refuses_protected_branch_without_any_http_call(tmp_path, protected):
    file_path = tmp_path / "learnings" / "2026-08-15.md"
    file_path.parent.mkdir()
    file_path.write_text("x")

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no HTTP call should be made when the target branch is protected")

    client = httpx.Client(base_url=github_publish.GITHUB_API_BASE, transport=httpx.MockTransport(handler))

    with pytest.raises(PublishError):
        publish_files(
            repo="org/repo",
            token="fake-token",
            base_branch="main",
            new_branch=protected,
            files=[file_path],
            commit_message="msg",
            pr_title="title",
            pr_body="body",
            repo_root=tmp_path,
            client=client,
        )


def test_publish_files_raises_on_empty_file_list(tmp_path):
    with pytest.raises(PublishError):
        publish_files(
            repo="org/repo",
            token="fake-token",
            base_branch="main",
            new_branch="learning-loop/2026-08-15",
            files=[],
            commit_message="msg",
            pr_title="title",
            pr_body="body",
            repo_root=tmp_path,
        )


def test_maybe_publish_is_noop_without_github_token(monkeypatch, tmp_path):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    file_path = tmp_path / "learnings" / "2026-08-15.md"
    file_path.parent.mkdir()
    file_path.write_text("x")

    result = maybe_publish([file_path], branch_suffix="2026-08-15", commit_message="m", pr_title="t", pr_body="b")

    assert result is None


def test_maybe_publish_delegates_to_publish_files_with_env_token(monkeypatch, tmp_path):
    monkeypatch.setenv("GITHUB_TOKEN", "fake-token")
    monkeypatch.setenv("GITHUB_REPO", "org/repo")
    file_path = tmp_path / "learnings" / "2026-08-15.md"
    file_path.parent.mkdir()
    file_path.write_text("x")

    captured = {}

    def fake_publish_files(**kwargs):
        captured.update(kwargs)
        return github_publish.PublishResult(branch=kwargs["new_branch"], pr_url="https://example.com/pr/1")

    monkeypatch.setattr(github_publish, "publish_files", fake_publish_files)

    result = maybe_publish([file_path], branch_suffix="2026-08-15", commit_message="m", pr_title="t", pr_body="b")

    assert result is not None
    assert result.branch == "learning-loop/2026-08-15"
    assert captured["repo"] == "org/repo"
    assert captured["token"] == "fake-token"
    assert captured["new_branch"] == "learning-loop/2026-08-15"
