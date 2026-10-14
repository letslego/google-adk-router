"""Deterministic episodic capture for explicit user requests, independent of model routing."""
import hashlib
import re
from .service import MemoryWrite

_REQUEST = re.compile(r'^(?:(?:please|can you|could you|would you|will you)\s+)*(?:remember\b|(?:save|store|record)\s+(?:(?:this|that)\s+)?(?:in (?:my |your )?memory\b|as (?:an? )?(?:episodic )?memory\b|(?:fact|preference|event|memory)\b))', re.I)
_RECALL = re.compile(r'^remember\s+(?:what|when|where|who|which|whether|how|if)\b', re.I)
_SECRET = re.compile(r'(?:sk-ant-[\w-]{20,}|AIza[\w-]{25,}|gh[pousr]_[\w]{20,}|-----BEGIN .*PRIVATE KEY-----|\b(?:password|api[_ -]?key|access[_ -]?token)\s*(?:is|:|=)\s*\S+)', re.I)


def explicit_remember_request(text):
    text=text.strip()
    return bool(_REQUEST.match(text)) and not bool(_RECALL.match(text))


def request_episode(session_id, invocation_id, text):
    """One stable episode per root invocation; preserve the user's exact unverified statement."""
    if not explicit_remember_request(text) or _SECRET.search(text):
        return None
    key='remember_'+hashlib.sha256(f'{session_id}:{invocation_id}'.encode()).hexdigest()
    return MemoryWrite(key=key,text=text,kind='episodic',metadata={
        'source':'explicit_user_remember_request','session_id':session_id,
        'request_id':invocation_id,'evidence_status':'user_stated_unverified'})
