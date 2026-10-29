"""Deterministic web extraction quality heuristics (no LLM)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

CHALLENGE_MARKERS = (
    "sign in to x",
    "sign in to twitter",
    "log in to x",
    "javascript is disabled",
    "javascript is not available",
    "something went wrong",
    "verify you are human",
    "cookies policy",
)

NAV_SHELL_MARKERS = (
    "home timeline",
    "explore",
    "notifications",
    "messages",
    "grok",
    "premium",
    "communities",
    "bookmarks",
    "post",
)

TWEET_HOST_SUFFIXES = ("x.com", "twitter.com", "mobile.twitter.com")


@dataclass(frozen=True)
class WebQualityAssessment:
    needs_browser: bool
    low_quality: bool
    challenge: bool
    reason_code: str | None
    user_message: str | None


def assess_web_extraction(url: str, html: str, blocks: list[str], script_count: int) -> WebQualityAssessment:
    visible = "\n\n".join(blocks).strip()
    lowered_html = (html or "")[:8000].lower()
    lowered_visible = visible.lower()
    host = (urlsplit(url).hostname or "").lower()

    if _is_challenge_page(lowered_html, lowered_visible):
        return WebQualityAssessment(
            needs_browser=False,
            low_quality=True,
            challenge=True,
            reason_code="WEB_AUTH_OR_CHALLENGE",
            user_message="页面需要登录或验证，无法获取公开正文。",
        )

    if visible and script_count == 0 and len(visible) >= 40:
        if not _is_tweet_host(host):
            return WebQualityAssessment(False, False, False, None, None)
        if not _twitter_nav_shell(lowered_visible, blocks):
            return WebQualityAssessment(False, False, False, None, None)

    if script_count > 0 and len(visible) < 40:
        return WebQualityAssessment(True, True, False, "NEEDS_BROWSER_EXTRACTION", None)

    if _is_tweet_host(host) and script_count > 0:
        if len(visible) < 120 or _twitter_nav_shell(lowered_visible, blocks):
            return WebQualityAssessment(True, True, False, "NEEDS_BROWSER_EXTRACTION", None)

    if _is_tweet_host(host) and _twitter_nav_shell(lowered_visible, blocks) and len(visible) < 500:
        return WebQualityAssessment(
            True,
            True,
            False,
            "NEEDS_BROWSER_EXTRACTION",
            "静态页面主要是导航信息，尝试浏览器渲染。",
        )

    if not visible:
        return WebQualityAssessment(script_count > 0, True, False, "NEEDS_BROWSER_EXTRACTION", None)

    return WebQualityAssessment(False, False, False, None, None)


def static_shell_needs_browser(blocks: list[str], script_count: int, url: str = "", html: str = "") -> bool:
    if script_count > 0 and len("\n\n".join(blocks).strip()) < 40:
        return True
    if url or html:
        return assess_web_extraction(url, html, blocks, script_count).needs_browser
    return False


def _is_tweet_host(host: str) -> bool:
    if not host:
        return False
    return host in TWEET_HOST_SUFFIXES or host.endswith(".x.com") or host.endswith(".twitter.com")


def _is_challenge_page(html_lower: str, visible_lower: str) -> bool:
    if "sign in to x" in visible_lower or "sign in to twitter" in visible_lower:
        return True
    sample = f"{visible_lower}\n{html_lower[:2000]}"
    hits = sum(1 for marker in CHALLENGE_MARKERS if marker in sample)
    if hits >= 2:
        return True
    if "sign in" in sample and ("x.com" in sample or "twitter" in sample):
        return True
    return False


def _twitter_nav_shell(visible_lower: str, blocks: list[str]) -> bool:
    nav_hits = sum(1 for marker in NAV_SHELL_MARKERS if marker in visible_lower)
    if nav_hits >= 4:
        return True
    if len(blocks) >= 8 and len(visible_lower) > 200:
        short_blocks = sum(1 for block in blocks if len(block.strip()) < 24)
        if short_blocks / max(len(blocks), 1) > 0.7:
            return True
    return False
