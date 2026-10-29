import json
import re

from app.services.analysis.schema import extract_json_object

FOCUSED = "FOCUSED"
COVERAGE = "COVERAGE"

ANSWER_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "answer": {"type": "string"},
        "citations": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "chunk_id": {"type": "string"},
                    "quote": {"type": "string"},
                },
                "required": ["chunk_id", "quote"],
            },
        },
    },
    "required": ["answer", "citations"],
}

PLAN_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "mode": {"type": "string", "enum": [FOCUSED, COVERAGE]},
        "needs_cross_source": {"type": "boolean"},
        "requested_scope": {"type": "string", "enum": ["CURRENT_FILTER_SCOPE"]},
        "reason": {"type": "string", "maxLength": 120},
    },
    "required": ["mode", "needs_cross_source", "requested_scope", "reason"],
}


def parse_plan(text: str) -> dict | None:
    try:
        data = extract_json_object(text)
    except (ValueError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    mode = str(data.get("mode") or "").upper()
    if mode not in {FOCUSED, COVERAGE}:
        return None
    if str(data.get("requested_scope") or "") != "CURRENT_FILTER_SCOPE":
        return None
    return {
        "mode": mode,
        "needs_cross_source": bool(data.get("needs_cross_source")),
        "requested_scope": "CURRENT_FILTER_SCOPE",
        "reason": str(data.get("reason") or "")[:300],
    }


def allocate_coverage(groups: list[list[dict]], *, slots: int, minimum: int, maximum: int) -> list[dict]:
    if slots <= 0 or maximum <= 0 or not groups:
        return []
    chosen: list[dict] = []
    cursors = [0] * len(groups)
    counts = [0] * len(groups)
    for _round in range(max(minimum, 1)):
        for index, group in enumerate(groups):
            if len(chosen) >= slots:
                return chosen
            if counts[index] >= maximum or cursors[index] >= len(group):
                continue
            chosen.append(group[cursors[index]])
            cursors[index] += 1
            counts[index] += 1
    leftover: list[tuple[dict, int]] = []
    for index, group in enumerate(groups):
        leftover.extend((item, index) for item in group[cursors[index] :])
    leftover.sort(key=lambda pair: float(pair[0].get("score") or 0), reverse=True)
    for item, index in leftover:
        if len(chosen) >= slots or counts[index] >= maximum:
            continue
        chosen.append(item)
        counts[index] += 1
    return chosen


def representative_utility(distance: float, length: int) -> float:
    closeness = 1.0 - min(max(distance, 0.0), 1.0)
    return closeness * min(max(length, 0), 1200) / 1200


def select_fallback_candidates(groups: list[list[dict]], *, maximum: int) -> list[list[dict]]:
    counts: dict[str, int] = {}
    for group in groups:
        seen: set[str] = set()
        for item in group:
            if item.get("retrieval_reason") != "COVERAGE_FALLBACK":
                continue
            key = str(item.get("text_key") or "")
            if key and key not in seen:
                counts[key] = counts.get(key, 0) + 1
                seen.add(key)
    selected: list[list[dict]] = []
    for group in groups:
        relevance = [item for item in group if item.get("retrieval_reason") != "COVERAGE_FALLBACK"]
        if relevance:
            selected.append(relevance[:maximum])
            continue
        unique = [item for item in group if counts.get(str(item.get("text_key") or ""), 0) <= 1]
        pool = unique or list(group)
        pool.sort(key=lambda item: float(item.get("score") or 0), reverse=True)
        selected.append(pool[:maximum])
    return [group for group in selected if group]


def coverage_slots(populated: int, *, slot_budget: int, per_source_cap: int) -> int:
    if populated <= 0:
        return 0
    slots = populated if populated > slot_budget else slot_budget
    return min(slots, populated * max(per_source_cap, 1))


def overclaims_unretrieved(answer: str, eligible: int, retrieved: int) -> bool:
    if eligible <= 1 or retrieved >= eligible:
        return False
    compact = re.sub(r"\s+", "", answer or "")
    needles = [
        f"这{eligible}条",
        f"{eligible}条资料都",
        f"{eligible}条都",
        f"全部{eligible}条",
        f"所有{eligible}条",
    ]
    if eligible == 3:
        needles.extend(["三条都", "这三条资料都", "这三条都可以", "三条资料都"])
    if any(item in compact for item in needles):
        return True
    return re.search(rf"\ball\s+{eligible}\b", answer or "", re.IGNORECASE) is not None


def coverage_notice(*, eligible: int, retrieved: int, limit: int, limited: bool, missing_titles: list[str]) -> str:
    parts: list[str] = []
    if limited:
        parts.append(f"当前范围有 {eligible} 条资料，超过单次覆盖上限 {limit}。本次只覆盖其中 {retrieved} 条，不能代表其余资料。")
    elif retrieved < eligible:
        parts.append(f"目前只检索到其中 {retrieved} 条的有效证据，无法判断另外 {eligible - retrieved} 条。")
    if missing_titles:
        parts.append("没有可用正文的资料：" + "、".join(missing_titles) + "。")
    return "".join(parts)


def apply_coverage_contract(
    answer: str,
    *,
    mode: str,
    eligible: int,
    retrieved: int,
    limit: int,
    limited: bool,
    missing_titles: list[str],
) -> tuple[str, str | None]:
    if mode != COVERAGE:
        return answer, None
    if overclaims_unretrieved(answer, eligible, retrieved):
        notice = coverage_notice(eligible=eligible, retrieved=retrieved, limit=limit, limited=limited, missing_titles=missing_titles)
        return notice or "目前检索到的资料不足以覆盖所问范围。", "COVERAGE_SCOPE"
    if limited or retrieved < eligible or missing_titles:
        notice = coverage_notice(eligible=eligible, retrieved=retrieved, limit=limit, limited=limited, missing_titles=missing_titles)
        if notice and notice not in (answer or ""):
            answer = f"{notice}\n\n{answer}".strip()
        return answer, "PARTIAL_COVERAGE"
    return answer, None
