"""Custom memory service with a replaceable repository and persistent SQLite default."""
from contextlib import contextmanager
import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol, Literal
from functools import lru_cache
from pydantic import BaseModel, ConfigDict, Field

class MemoryWrite(BaseModel):
    model_config = ConfigDict(extra='forbid')
    key: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,100}$')
    text: str = Field(min_length=1, max_length=20000)
    metadata: dict = Field(default_factory=dict)
    kind: Literal['short_term', 'long_term', 'episodic', 'semantic', 'procedural', 'working', 'profile', 'knowledge', 'operational'] = 'long_term'
    session_id: str = Field(default='', max_length=200)

class MemoryRepository(Protocol):
    def put(self, app: str, user: str, memory: MemoryWrite) -> dict: ...
    def search(self, app: str, user: str, query: str, limit: int, kind: str = 'long_term', session_id: str = '') -> list[dict]: ...
    def delete(self, app: str, user: str, key: str, kind: str = 'long_term', session_id: str = '') -> bool: ...

class SQLiteMemoryRepository:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('''CREATE TABLE IF NOT EXISTS custom_memory_v2 (
                app TEXT NOT NULL, user TEXT NOT NULL, key TEXT NOT NULL,
                text TEXT NOT NULL, metadata TEXT NOT NULL, updated_at TEXT NOT NULL,
                kind TEXT NOT NULL, session_id TEXT NOT NULL,
                PRIMARY KEY (app, user, kind, session_id, key))''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def record(row):
        return {'key': row['key'], 'text': row['text'], 'metadata': json.loads(row['metadata']),
                'updated_at': row['updated_at'], 'kind': row['kind'], 'session_id': row['session_id']}

    def put(self, app, user, memory):
        updated = datetime.now(timezone.utc).isoformat()
        metadata = json.dumps(memory.metadata, allow_nan=False)
        if len(metadata.encode()) > 20000:
            raise ValueError('Metadata exceeds 20 KB')
        with self.connect() as db:
            db.execute('''INSERT INTO custom_memory_v2 VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(app,user,kind,session_id,key) DO UPDATE SET text=excluded.text,
                metadata=excluded.metadata, updated_at=excluded.updated_at''',
                (app, user, memory.key, memory.text, metadata, updated, memory.kind, memory.session_id))
        return {**memory.model_dump(), 'updated_at': updated}

    def search(self, app, user, query, limit, kind='long_term', session_id=''):
        tokens = list(dict.fromkeys(re.findall(r'\w+', query.lower())))[:20]
        sql = 'SELECT * FROM custom_memory_v2 WHERE app=? AND user=? AND kind=? AND session_id=?'
        params = [app, user, kind, session_id]
        for token in tokens:
            sql += ' AND lower(text || \' \' || key) LIKE ? ESCAPE \'\\\''
            params.append('%' + token.replace('\\', '\\\\').replace('_', '\\_') + '%')
        sql += ' ORDER BY updated_at DESC, key LIMIT ?'
        params.append(limit)
        with self.connect() as db:
            return [self.record(row) for row in db.execute(sql, params)]

    def delete(self, app, user, key, kind='long_term', session_id=''):
        with self.connect() as db:
            return db.execute('DELETE FROM custom_memory_v2 WHERE app=? AND user=? AND key=? AND kind=? AND session_id=?', (app,user,key,kind,session_id)).rowcount > 0

class MemoryService:
    def __init__(self, repository: MemoryRepository):
        self.repository = repository

    @staticmethod
    def scope(app, user):
        if not app or not user or len(app) > 200 or len(user) > 200:
            raise ValueError('Nonempty application and user IDs up to 200 characters required')

    @staticmethod
    def partition(kind, session_id):
        if kind not in {'short_term', 'long_term', 'episodic', 'semantic', 'procedural', 'working', 'profile', 'knowledge', 'operational'}:
            raise ValueError('Unknown memory kind')
        if kind in {'short_term', 'working'} and not session_id:
            raise ValueError('Short-term memory requires a session ID')
        if kind not in {'short_term', 'working'} and session_id:
            raise ValueError('Long-term memory is not session-partitioned')

    def store(self, app, user, memory: MemoryWrite):
        self.scope(app, user)
        self.partition(memory.kind, memory.session_id)
        if not memory.text.strip():
            raise ValueError('Memory text cannot be blank')
        return self.repository.put(app, user, memory)

    def retrieve(self, app, user, query='', limit=10, kind='long_term', session_id=''):
        self.scope(app, user)
        self.partition(kind, session_id)
        if len(query) > 2000 or not 1 <= limit <= 50:
            raise ValueError('Query max 2000 characters; limit 1-50')
        return self.repository.search(app, user, query, limit, kind, session_id)

    def forget(self, app, user, key, kind='long_term', session_id=''):
        self.scope(app, user)
        self.partition(kind, session_id)
        return self.repository.delete(app, user, key, kind, session_id)

@lru_cache(maxsize=1)
def get_memory_service():
    if os.getenv('MEMORY_BACKEND', 'sqlite') == 'memlayer':
        from .memlayer import MemLayerRepository
        return MemoryService(MemLayerRepository(os.getenv('MEMLAYER_URL', 'http://127.0.0.1:61002')))
    if os.getenv('MEMORY_BACKEND', 'sqlite') == 'memorylayer':
        from .scitrera import MemoryLayerRepository
        return MemoryService(MemoryLayerRepository(os.getenv('MEMORYLAYER_URL', 'http://127.0.0.1:61001')))
    default = Path(__file__).resolve().parents[1] / '.adk/custom-memory.sqlite3'
    return MemoryService(SQLiteMemoryRepository(Path(os.getenv('CUSTOM_MEMORY_DB', str(default)))))
