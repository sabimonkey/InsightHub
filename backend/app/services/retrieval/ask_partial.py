"""Extract provisional answer text from a growing JSON_OBJECT response."""

import json
import re

_ANSWER_PREFIX = re.compile(r'"answer"\s*:\s*"', re.DOTALL)


def partial_answer_text(buffer: str) -> str:
    match = _ANSWER_PREFIX.search(buffer)
    if not match:
        return ""
    raw = buffer[match.end() :]
    out: list[str] = []
    i = 0
    while i < len(raw):
        ch = raw[i]
        if ch == '"':
            break
        if ch == "\\" and i + 1 < len(raw):
            nxt = raw[i + 1]
            if nxt == "n":
                out.append("\n")
            elif nxt == "t":
                out.append("\t")
            elif nxt == '"':
                out.append('"')
            elif nxt == "\\":
                out.append("\\")
            else:
                out.append(nxt)
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)
