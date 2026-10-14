"""Deterministic episodic capture for explicit user requests, independent of model routing."""
import hashlib
import re
from .service import MemoryWrite

# Match direct user instructions, not arbitrary mentions inside supplied documents.
_POLITE = re.compile(r"^(?:(?:please|can you|could you|would you|will you|i want you to|i need you to|i would like you to|i'd like you to)\s+)+", re.I)
_REQUEST = re.compile(
    r"^(?:remember\b|memorize\b|keep (?:this )?in mind\b|bear in mind\b|"
    r"(?:do not|don't) forget(?:\s+that)?\b|"
    r"(?:make|take) a note(?:\s+of)?\b|take note(?:\s+of)?\b|"
    r"note (?:that\b|this down\b|this:)|jot (?:this |that )?down\b|"
    r"keep a record of\b|file this away\b|keep (?:this|that) for future reference\b|"
    r"(?:save|store|retain) (?:this|that) for (?:later|future reference)\b|"
    r"(?:add|commit) (?:this |that )?to (?:my |your )?memory\b|"
    r"(?:save|store|record|log|retain)\s+(?:"
    r"(?:this|that)\s+(?:(?:in|to) (?:my |your )?memory\b|as (?:an? )?(?:episodic )?memory\b)|"
    r"(?:(?:in|to) (?:my |your )?memory\b|as (?:an? )?(?:episodic )?memory\b)|"
    r"(?:this )?(?:fact|preference|event|memory)\b|that\s+|this\s*:))", re.I)
_RECALL = re.compile(r"^(?:what|when|where|who|which|whether|how|if)\b", re.I)
_EXTERNAL_ACTION = re.compile(r"^(?:to\s+|(?:this|the|a)\s+(?:file|report|document|video|audio|image|log)\b)", re.I)
_SECRET = re.compile(r'(?:sk-ant-[\w-]{20,}|AIza[\w-]{25,}|gh[pousr]_[\w]{20,}|-----BEGIN .*PRIVATE KEY-----|\b(?:password|api[_ -]?key|access[_ -]?token)\s*(?:is|:|=)\s*\S+)', re.I)


def explicit_remember_request(text):
    text=text.strip().replace("’", "'")
    text=_POLITE.sub('',text)
    match=_REQUEST.match(text)
    if not match:
        return False
    remainder=text[match.end():].lstrip(' :,-')
    return bool(remainder) and not bool(_RECALL.match(remainder) or _EXTERNAL_ACTION.match(remainder))



def request_episode(session_id, invocation_id, text):
    """One stable episode per root invocation; preserve the user's exact unverified statement."""
    if not explicit_remember_request(text) or _SECRET.search(text):
        return None
    key='remember_'+hashlib.sha256(f'{session_id}:{invocation_id}'.encode()).hexdigest()
    return MemoryWrite(key=key,text=text,kind='episodic',metadata={
        'source':'explicit_user_remember_request','session_id':session_id,
        'request_id':invocation_id,'evidence_status':'user_stated_unverified'})
