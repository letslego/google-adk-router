from datetime import datetime, timezone


def utc_time() -> dict:
    """Get the current UTC time for questions about dates or time."""
    return {"utc": datetime.now(timezone.utc).isoformat()}


def text_statistics(text: str) -> dict:
    """Count words, characters, and lines in supplied text."""
    return {"words": len(text.split()), "characters": len(text), "lines": len(text.splitlines())}


TOOLS = {"utc_time": utc_time, "text_statistics": text_statistics}
