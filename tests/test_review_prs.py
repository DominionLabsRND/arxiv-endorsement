"""Tests for the pull-request handling in review_prs.py (no network)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


review_prs = _load(ROOT / "scripts" / "review_prs.py", "review_prs")

WRONG_SUBJECT = "LinkedIn: https://www.linkedin.com/in/someone\nPaper: https://example.org/p.pdf\nRepo: https://github.com/someone/repo\nSubject: cs.AI\nEndorsementCode: A1B2C3\n"
MALFORMED = "LinkedIn: https://www.linkedin.com/in/someone\nSubject: cs.SE\n"

PR = {"number": 42, "files": [{"path": "requests/someone.txt"}], "headRefOid": "deadbeef"}


@pytest.fixture
def stubbed(monkeypatch):
    calls: dict[str, list] = {"comments": [], "closed": [], "commented_markers": []}
    monkeypatch.setattr(review_prs, "post_comment", lambda repo, n, body: calls["comments"].append((n, body)))
    monkeypatch.setattr(review_prs, "already_commented", lambda repo, n, marker=review_prs.COMMENT_MARKER: False)

    def fake_close(repo, n, body):
        calls["comments"].append((n, body))
        calls["closed"].append(n)

    monkeypatch.setattr(review_prs, "close_pr", fake_close)
    return calls


def test_wrong_subject_pr_is_closed_with_the_automated_reply(stubbed, monkeypatch):
    monkeypatch.setattr(review_prs, "fetch_file_content", lambda repo, path, ref: WRONG_SUBJECT)
    review_prs.process_pr("owner/repo", PR, dry_run=False, update=False)
    assert stubbed["closed"] == [42]
    (_, body), = stubbed["comments"]
    assert review_prs.WRONG_SUBJECT_MESSAGE in body
    assert review_prs.WRONG_SUBJECT_MARKER in body


def test_wrong_subject_pr_is_not_closed_in_dry_run(stubbed, monkeypatch):
    monkeypatch.setattr(review_prs, "fetch_file_content", lambda repo, path, ref: WRONG_SUBJECT)
    review_prs.process_pr("owner/repo", PR, dry_run=True, update=False)
    assert stubbed["closed"] == []
    assert stubbed["comments"] == []


def test_wrong_subject_pr_is_answered_only_once(stubbed, monkeypatch):
    monkeypatch.setattr(review_prs, "fetch_file_content", lambda repo, path, ref: WRONG_SUBJECT)
    monkeypatch.setattr(
        review_prs, "already_commented",
        lambda repo, n, marker=review_prs.COMMENT_MARKER: marker == review_prs.WRONG_SUBJECT_MARKER,
    )
    review_prs.process_pr("owner/repo", PR, dry_run=False, update=False)
    assert stubbed["closed"] == []
    assert stubbed["comments"] == []


def test_other_validation_errors_leave_the_pr_open(stubbed, monkeypatch):
    monkeypatch.setattr(review_prs, "fetch_file_content", lambda repo, path, ref: MALFORMED)
    review_prs.process_pr("owner/repo", PR, dry_run=False, update=False)
    assert stubbed["closed"] == []
    assert stubbed["comments"] == []
