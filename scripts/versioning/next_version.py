#!/usr/bin/env python3
"""Compute the next SemVer from Conventional Commits since the latest v* tag."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
VERSION_FILE = ROOT / "VERSION"
TAG_PATTERN = re.compile(r"^v(?P<version>\d+\.\d+\.\d+)$")
COMMIT_HEADER = re.compile(
    r"^(?P<type>[a-z]+)(?:\([^)]+\))?(?P<breaking>!)?:\s",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Version:
    major: int
    minor: int
    patch: int

    @classmethod
    def parse(cls, value: str) -> Version:
        match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", value.strip())
        if not match:
            raise ValueError(f"Invalid version: {value!r}")
        return cls(int(match.group(1)), int(match.group(2)), int(match.group(3)))

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"

    def bump_major(self) -> Version:
        return Version(self.major + 1, 0, 0)

    def bump_minor(self) -> Version:
        return Version(self.major, self.minor + 1, 0)

    def bump_patch(self) -> Version:
        return Version(self.major, self.minor, self.patch + 1)


def run_git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True, cwd=ROOT).strip()


def latest_version_tag() -> str | None:
    tags = run_git("tag", "--list", "v*").splitlines()
    versions: list[tuple[Version, str]] = []
    for tag in tags:
        match = TAG_PATTERN.match(tag)
        if match:
            versions.append((Version.parse(match.group("version")), tag))
    if not versions:
        return None
    versions.sort(key=lambda item: item[0])
    return versions[-1][1]


def current_version() -> Version:
    tag = latest_version_tag()
    if tag:
        return Version.parse(TAG_PATTERN.match(tag).group("version"))  # type: ignore[union-attr]
    if VERSION_FILE.is_file():
        return Version.parse(VERSION_FILE.read_text(encoding="utf-8"))
    return Version(0, 1, 0)


def commits_since(tag: str | None) -> list[str]:
    if tag:
        args = ["log", f"{tag}..HEAD", "--format=%B%x00"]
    else:
        args = ["log", "--format=%B%x00"]
    output = run_git(*args)
    if not output:
        return []
    return [entry.strip() for entry in output.split("\x00") if entry.strip()]


def subject_line(message: str) -> str:
    for line in message.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def classify_commit(message: str) -> str:
    subject = subject_line(message)
    header_match = COMMIT_HEADER.match(subject)
    if not header_match:
        return "other"

    commit_type = header_match.group("type").lower()
    if header_match.group("breaking") == "!":
        return "breaking"

    body = "\n".join(
        line.strip()
        for line in message.splitlines()[1:]
        if line.strip()
    )
    if re.search(r"(?m)^BREAKING CHANGE:\s", body):
        return "breaking"

    if commit_type == "feat":
        return "feat"
    if commit_type == "fix":
        return "fix"
    return "other"


def next_version(current: Version, commits: list[str]) -> Version:
    bump = "patch"
    for message in commits:
        kind = classify_commit(message)
        if kind == "breaking":
            bump = "major"
            break
        if kind == "feat":
            bump = "minor"
        elif kind == "fix" and bump == "patch":
            bump = "patch"

    if bump == "major":
        return current.bump_major()
    if bump == "minor":
        return current.bump_minor()
    return current.bump_patch()


def write_version(version: Version) -> None:
    VERSION_FILE.write_text(f"{version}\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write the computed version to VERSION.",
    )
    args = parser.parse_args()

    tag = latest_version_tag()
    current = current_version()
    commits = commits_since(tag)
    version = next_version(current, commits)

    if args.write:
        write_version(version)

    print(version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
