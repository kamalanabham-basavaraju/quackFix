from pathlib import Path
from types import SimpleNamespace

import pytest

from app.integrations.git.client import GitClient, GitError


def test_push_branch_uses_token_auth_without_leaking_token(monkeypatch, tmp_path: Path):
    captured = {}

    def fake_run(args, cwd, text, capture_output, check, timeout, env):
        captured.update(
            {
                "args": args,
                "cwd": cwd,
                "text": text,
                "capture_output": capture_output,
                "check": check,
                "timeout": timeout,
                "env": env,
            }
        )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("app.integrations.git.client.subprocess.run", fake_run)

    GitClient(tmp_path).push_branch("ai/test-branch", "secret-token")

    assert captured["cwd"] == tmp_path
    assert captured["args"][0:2] == ["git", "-c"]
    assert "secret-token" not in " ".join(captured["args"])
    assert captured["args"][-4:] == ["push", "--set-upstream", "origin", "ai/test-branch"]


def test_assert_push_access_rejects_read_only_token(monkeypatch, tmp_path: Path):
    client = GitClient(tmp_path)
    monkeypatch.setattr(client, "_github_owner_repo", lambda: ("owner", "repo"))

    class Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"permissions": {"pull": True, "push": False, "admin": False}}

    monkeypatch.setattr("app.integrations.git.client.requests.get", lambda *args, **kwargs: Response())

    with pytest.raises(GitError, match="does not have push/write access"):
        client.assert_push_access("token")
