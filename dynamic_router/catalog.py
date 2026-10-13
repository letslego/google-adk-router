import json
import re
from pathlib import Path

from .tools import TOOLS

BASE = Path(__file__).parent


def validate_agent(spec: dict) -> dict:
    required = {"name", "description", "instruction", "tools", "skills"}
    if not required <= spec.keys():
        raise ValueError(f"Agent requires {sorted(required)}")
    if not isinstance(spec["name"], str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", spec["name"]):
        raise ValueError("Invalid agent name")
    for field in ("description", "instruction"):
        if not isinstance(spec[field], str) or not spec[field].strip():
            raise ValueError(f"Invalid {field}")
    for field in ("tools", "skills"):
        if not isinstance(spec[field], list) or not all(isinstance(x, str) for x in spec[field]):
            raise ValueError(f"Invalid {field}")
    if set(spec["tools"]) - TOOLS.keys():
        raise ValueError("Unknown tool in manifest")
    if set(spec["skills"]) - skills().keys():
        raise ValueError("Unknown skill in manifest")
    return spec


def agents() -> dict:
    result = {}
    for path in sorted((BASE / "catalog").glob("*.json")):
        if path.name == "graphs.json":
            continue
        spec = validate_agent(json.loads(path.read_text()))
        if spec["name"] in result:
            raise ValueError("Duplicate agent name")
        result[spec["name"]] = spec
    return result


def skills() -> dict:
    result = {}
    for path in sorted((BASE / "skills").glob("*/SKILL.md")):
        text = path.read_text()
        header = text.split("---", 2)
        if len(header) < 3:
            raise ValueError(f"Missing frontmatter: {path}")
        metadata = dict(line.split(":", 1) for line in header[1].strip().splitlines())
        name = metadata["name"].strip()
        if name != path.parent.name or name in result:
            raise ValueError(f"Invalid/duplicate skill: {path}")
        result[name] = {"name": name, "description": metadata["description"].strip(), "body": header[2].strip()}
    return result


def graphs() -> dict:
    return json.loads((BASE / "catalog" / "graphs.json").read_text())


def validate_path(graph: dict, path: list[str], available: dict) -> None:
    if not path or len(path) > 8 or path[0] != graph["start"] or path[-1] not in graph["ends"]:
        raise ValueError("Path must start/end at declared nodes and contain at most 8 nodes")
    if any(node not in available for node in path):
        raise ValueError("Unknown agent in path")
    if len(set(path)) != len(path):
        raise ValueError("Cycles are not allowed")
    if any(b not in graph["edges"].get(a, []) for a, b in zip(path, path[1:])):
        raise ValueError("Path contains a forbidden edge")
