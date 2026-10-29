#!/usr/bin/env python3
"""Check local Markdown links, image targets, Mermaid fences, and env references."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = [ROOT / "README.md", ROOT / "README.zh-CN.md", *sorted((ROOT / "docs").rglob("*.md"))]
LINK_RE = re.compile(r"(?<!!)\[[^\]]*\]\(([^)]+)\)|!\[[^\]]*\]\(([^)]+)\)")
ENV_RE = re.compile(r"\b[A-Z][A-Z0-9_]{3,}\b")


def check_links(path: Path, text: str) -> list[str]:
    issues: list[str] = []
    for match in LINK_RE.finditer(text):
        target = (match.group(1) or match.group(2) or "").split()[0].strip("<>")
        if not target or target.startswith(("https://", "http://", "mailto:", "#")):
            continue
        local, _, fragment = target.partition("#")
        resolved = (path.parent / local).resolve() if local else path
        if not resolved.exists():
            issues.append(f"{path.relative_to(ROOT)}: missing link target {target}")
        elif fragment and resolved.suffix.lower() in {".md", ".markdown"}:
            content = resolved.read_text(encoding="utf-8")
            slug = fragment.lower()
            headings = {
                re.sub(r"[^\w\- ]", "", h.group(1).lower()).strip().replace(" ", "-")
                for h in re.finditer(r"^#+\s+(.+)$", content, re.M)
            }
            if slug not in headings:
                issues.append(f"{path.relative_to(ROOT)}: missing heading #{fragment} in {target}")
    return issues


def main() -> int:
    issues: list[str] = []
    for path in DOCS:
        text = path.read_text(encoding="utf-8")
        issues.extend(check_links(path, text))
        if text.count("```") % 2:
            issues.append(f"{path.relative_to(ROOT)}: unclosed fenced code block")
        if text.count("```mermaid") > text.count("```") // 2:
            issues.append(f"{path.relative_to(ROOT)}: malformed Mermaid fence")
    declared: set[str] = set()
    for env_template in ROOT.glob(".env.*.example"):
        declared.update(re.findall(r"^([A-Z][A-Z0-9_]*)=", env_template.read_text(encoding="utf-8"), re.M))
    config = (ROOT / "backend/app/core/config.py").read_text(encoding="utf-8")
    declared.update(name.upper() for name in re.findall(r"^\s{4}([a-z][a-z0-9_]+):\s", config, re.M))
    documented = set()
    for path in DOCS:
        documented.update(ENV_RE.findall(path.read_text(encoding="utf-8")))
    # Report undeclared-looking names for review rather than failing: API/DB/schema constants
    # are also uppercase and not every operational setting belongs in the Docker template.
    candidate = sorted(name for name in documented if name.endswith(("URL", "_PORT", "_KEY", "_MODEL", "_ENABLED", "_BUDGET")) and name not in declared)
    print(f"checked_markdown={len(DOCS)} local_link_issues={len(issues)} known_environment_names={len(declared)}")
    for issue in issues:
        print(f"ERROR {issue}")
    for name in candidate:
        print(f"REVIEW env name not in Docker template: {name}")
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
