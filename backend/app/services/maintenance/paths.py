from pathlib import Path


def resolve_under(root: Path, relative: str) -> Path:
    base = root.resolve()
    candidate = (base / relative).resolve()
    if candidate != base and base not in candidate.parents:
        raise ValueError("PATH_OUTSIDE_ROOT")
    return candidate
