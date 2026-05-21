#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROFILE_PATH = ROOT / "profile.json"
README_PATH = ROOT / "README.md"
USERNAME = "traktuner"


def github_get(path: str) -> object:
    token = os.getenv("GITHUB_TOKEN")
    curl = [
        "curl",
        "-fsSL",
        "-A",
        "traktuner-profile-generator",
        "-H",
        "Accept: application/vnd.github+json",
        "-H",
        "X-GitHub-Api-Version: 2022-11-28",
    ]
    if token:
        curl.extend(["-H", f"Authorization: Bearer {token}"])
    curl.append(f"https://api.github.com{path}")

    try:
        result = subprocess.run(curl, check=True, capture_output=True, text=True)
        return json.loads(result.stdout)
    except (subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f"GitHub API curl fallback failed for {path}: {exc}")
        return []


def public_repositories() -> list[dict]:
    repos: list[dict] = []
    page = 1
    while True:
        data = github_get(
            f"/users/{USERNAME}/repos?per_page=100&page={page}&sort=updated&type=owner"
        )
        if not isinstance(data, list) or not data:
            break
        repos.extend(repo for repo in data if isinstance(repo, dict))
        page += 1
    return repos


def repo_line(repo: dict) -> str:
    name = repo.get("name", "repository")
    url = repo.get("html_url", f"https://github.com/{USERNAME}/{name}")
    description = repo.get("description") or "Selected public project"
    language = repo.get("language") or "mixed"
    archived = " archived" if repo.get("archived") else ""
    return f"- [{name}]({url}) - {description} `({language}{archived})`"


def render(profile: dict, repos: list[dict]) -> str:
    active_repos = [repo for repo in repos if not repo.get("fork")]
    maintained = [
        repo
        for repo in active_repos
        if not repo.get("archived") and repo.get("name") != USERNAME
    ]
    recent = maintained[: int(profile.get("public_repo_limit", 5))]
    languages = Counter(repo.get("language") for repo in maintained if repo.get("language"))
    updated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    focus = "\n".join(f"- {item}" for item in profile["focus"])
    style = "\n".join(f"- {item}" for item in profile["working_style"])
    repo_lines = "\n".join(repo_line(repo) for repo in recent) or "- No public repository snapshot available right now."
    language_line = ", ".join(f"{name} ({count})" for name, count in languages.most_common(6))
    if not language_line:
        language_line = "No public language snapshot available right now."

    return f"""# {profile["name"]}

{profile["headline"]}

{profile["summary"]}

## Focus

{focus}

## Working Style

{style}

## Public Snapshot

{profile["note"]}

Recent public repositories:

{repo_lines}

Most common public repository languages: {language_line}

<sub>Profile generated from curated text and public GitHub metadata. Last updated: {updated_at}.</sub>
"""


def main() -> None:
    profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    repos = public_repositories()
    README_PATH.write_text(render(profile, repos), encoding="utf-8")


if __name__ == "__main__":
    main()
