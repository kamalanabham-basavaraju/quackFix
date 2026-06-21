from __future__ import annotations

import base64
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

_NO_PROMPT_ENV = {
    **os.environ,
    "GIT_TERMINAL_PROMPT": "0",
    "GCM_INTERACTIVE": "never",
    "GIT_ASKPASS": "echo",
}

DEFAULT_GIT_TIMEOUT = 60  # seconds


class GitError(RuntimeError):
    """Raised when a local Git operation fails."""


class GitClient:
    def __init__(self, project_path: Path, require_clean: bool = True):
        self.project_path = project_path
        self.require_clean = require_clean

    def _run(
        self, *args: str, check: bool = True, timeout: int = DEFAULT_GIT_TIMEOUT
    ) -> subprocess.CompletedProcess[str]:
        if shutil.which("git") is None:
            raise GitError("git executable is not installed or not available on PATH")
        try:
            return subprocess.run(
                ["git", *args],
                cwd=self.project_path,
                text=True,
                capture_output=True,
                check=check,
                timeout=timeout,
                env=_NO_PROMPT_ENV,
            )
        except subprocess.TimeoutExpired as exc:
            raise GitError(
                f"git {' '.join(args)} timed out after {timeout}s. This usually means git tried an "
                f"interactive credential prompt (terminal or GUI/browser login via Git Credential "
                f"Manager) that an automated process can never complete."
            ) from exc
        except (OSError, subprocess.CalledProcessError) as exc:
            stderr = getattr(exc, "stderr", None) or str(exc)
            if "dubious ownership" in stderr and "safe.directory" in stderr:
                raise GitError(
                    f"git {' '.join(args)} failed because Git does not trust {self.project_path}. "
                    f"Run `git config --global --add safe.directory {self.project_path}` in the runtime environment."
                ) from exc
            raise GitError(f"git {' '.join(args)} failed: {stderr.strip()}") from exc

    def ensure_repository(self) -> None:
        self._run("rev-parse", "--is-inside-work-tree")

    def ensure_clean(self) -> None:
        changed = self.changed_files()
        if changed:
            raise GitError(
                "Target repository has pre-existing changes; refusing to mix them with an incident run: "
                + ", ".join(changed)
            )

    def create_incident_branch(
        self,
        incident: str,
        branch_source: str | None = None,
        base_branch: str | None = None,
        now: datetime | None = None,
    ) -> str:
        self.ensure_repository()
        changed = self.changed_files()
        if changed and self.require_clean:
            self.ensure_clean()
        if base_branch and not changed:
            self._switch_to_base(base_branch)
        source = branch_source or incident
        slug = re.sub(r"[^a-z0-9]+", "-", source.lower()).strip("-")[:48] or "incident"
        timestamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%d-%H%M%S")
        branch = f"ai/{timestamp}-{slug}"
        self._run("switch", "-c", branch)
        return branch

    def _switch_to_base(self, base_branch: str) -> None:
        remotes = self._run("remote", check=False).stdout.split()
        if "origin" in remotes:
            self._run("fetch", "origin", base_branch, check=False)
            if self._run("show-ref", "--verify", f"refs/heads/{base_branch}", check=False).returncode != 0:
                tracked = self._run(
                    "show-ref", "--verify", f"refs/remotes/origin/{base_branch}", check=False
                )
                if tracked.returncode != 0:
                    return
                self._run("switch", "-c", base_branch, "--track", f"origin/{base_branch}")
            else:
                self._run("switch", base_branch)
                self._run("pull", "--ff-only", "origin", base_branch, check=False)
            return
        if self._run("show-ref", "--verify", f"refs/heads/{base_branch}", check=False).returncode == 0:
            self._run("switch", base_branch)

    def changed_files(self) -> list[str]:
        output = self._run("status", "--porcelain").stdout
        return sorted({line[3:].strip().strip('"') for line in output.splitlines() if len(line) > 3})

    def commit_all(self, message: str) -> str:
        if not self.changed_files():
            raise GitError("Enter Pro produced no changes to commit")
        self._run("add", "--all")
        self._run("commit", "-m", message)
        return self._run("rev-parse", "HEAD").stdout.strip()

    def push_branch(self, branch_name: str, token: str | None = None) -> None:
        if not token:
            # No token means git falls back to whatever local credential helper is
            # configured. On Windows that's typically Git Credential Manager, which
            # will try to pop a browser/GUI login for an unattended process - that
            # login can never be completed, so the push just hangs. In an automated
            # pipeline this should be a hard, immediate failure instead.
            raise GitError(
                "push_branch() was called without a token. An automated push cannot rely on an "
                "interactive credential helper (e.g. Git Credential Manager on Windows), as it will "
                "hang waiting on a login that can't be completed. Pass a GitHub token explicitly."
            )
        auth = base64.b64encode(f"x-access-token:{token}".encode("utf-8")).decode("ascii")
        try:
            subprocess.run(
                [
                    "git",
                    "-c",
                    f"http.https://github.com/.extraheader=AUTHORIZATION: basic {auth}",
                    "push",
                    "--set-upstream",
                    "origin",
                    branch_name,
                ],
                cwd=self.project_path,
                text=True,
                capture_output=True,
                check=True,
                timeout=DEFAULT_GIT_TIMEOUT,
                env=_NO_PROMPT_ENV,
            )
        except subprocess.TimeoutExpired as exc:
            raise GitError(
                f"git push --set-upstream origin {branch_name} timed out after {DEFAULT_GIT_TIMEOUT}s"
            ) from exc
        except (OSError, subprocess.CalledProcessError) as exc:
            stderr = getattr(exc, "stderr", None) or str(exc)
            if "The requested URL returned error: 403" in stderr or "Permission to" in stderr:
                raise GitError(
                    "GitHub rejected the branch push with 403. Check that GITHUB_TOKEN has write access to "
                    "this repository. Fine-grained tokens need Repository permissions: Contents read/write "
                    "and Pull requests read/write for the employee_portal repo."
                ) from exc
            raise GitError(f"git push --set-upstream origin {branch_name} failed: {stderr.strip()}") from exc

    def assert_push_access(
        self,
        token: str,
        api_url: str = "https://api.github.com",
    ) -> None:
        owner, repo = self._github_owner_repo()
        url = f"{api_url.rstrip('/')}/repos/{owner}/{repo}"
        try:
            response = requests.get(
                url,
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {token}",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                timeout=30,
            )
        except requests.RequestException as exc:
            raise GitError(f"GitHub token permission check failed: {exc}") from exc
        if response.status_code in {401, 403, 404}:
            raise GitError(
                f"GitHub token cannot access {owner}/{repo} with write permissions "
                f"(GitHub API returned {response.status_code}). Fine-grained tokens need Repository "
                "permissions: Contents read/write and Pull requests read/write for this repo."
            )
        try:
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise GitError(f"GitHub token permission check failed: {exc}") from exc
        permissions = payload.get("permissions") if isinstance(payload, dict) else {}
        if isinstance(permissions, dict) and not any(
            permissions.get(name) is True for name in ("push", "maintain", "admin")
        ):
            raise GitError(
                f"GitHub token can read {owner}/{repo}, but it does not have push/write access. "
                "Fine-grained tokens need Repository permissions: Contents read/write and Pull requests read/write."
            )

    def create_pull_request(
        self,
        token: str,
        branch_name: str,
        base_branch: str,
        title: str,
        body: str,
        api_url: str = "https://api.github.com",
    ) -> dict[str, Any]:
        owner, repo = self._github_owner_repo()
        url = f"{api_url.rstrip('/')}/repos/{owner}/{repo}/pulls"
        response = requests.post(
            url,
            json={"title": title, "head": branch_name, "base": base_branch, "body": body},
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30,
        )
        if response.status_code == 422:
            existing = self._find_existing_pull_request(token, branch_name, base_branch, api_url)
            if existing:
                return existing
        try:
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise GitError(f"GitHub pull request creation failed: {exc}") from exc
        if not isinstance(payload, dict):
            raise GitError("GitHub returned an unsupported pull request response")
        return payload

    def _find_existing_pull_request(
        self, token: str, branch_name: str, base_branch: str, api_url: str
    ) -> dict[str, Any] | None:
        owner, repo = self._github_owner_repo()
        url = f"{api_url.rstrip('/')}/repos/{owner}/{repo}/pulls"
        response = requests.get(
            url,
            params={"head": f"{owner}:{branch_name}", "base": base_branch, "state": "open"},
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30,
        )
        if not response.ok:
            return None
        payload = response.json()
        if isinstance(payload, list) and payload:
            return payload[0]
        return None

    def _github_owner_repo(self) -> tuple[str, str]:
        remote = self._run("remote", "get-url", "origin").stdout.strip()
        patterns = (
            r"github\.com[:/](?P<owner>[^/]+)/(?P<repo>[^/.]+)(?:\.git)?$",
            r"github\.com/(?P<owner>[^/]+)/(?P<repo>[^/.]+)(?:\.git)?$",
        )
        for pattern in patterns:
            match = re.search(pattern, remote)
            if match:
                return match.group("owner"), match.group("repo")
        raise GitError(f"Cannot parse GitHub owner/repo from origin remote: {remote}")
