"""SQLite write-through registries with cross-process cache invalidation."""
from contextlib import contextmanager
from dataclasses import dataclass
import copy
import json
from pathlib import Path
import re
import sqlite3
import threading
from typing import Callable


@dataclass(frozen=True)
class Scope:
    app: str
    user: str
    session: str

    def key(self):
        if not all(isinstance(v, str) and v.strip() for v in (self.app, self.user, self.session)):
            raise ValueError('Agent scope requires app, user and session')
        return json.dumps([self.app, self.user, self.session], separators=(',', ':'))


class RegistryService:
    """Stores JSON specifications, never Python functions or executable modules.

    Every connection uses durable SQLite commits. Version and row are read in one
    transaction so a concurrent writer cannot publish a row under an old version.
    Returned dictionaries are copies: callers cannot mutate the cached values.
    Scope must be derived from authenticated server context by the caller.
    """
    KINDS = {'agent', 'skill', 'tool'}

    def __init__(self, path: str | Path, approved_tools: dict[str, Callable] | None = None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.approved_tools = dict(approved_tools or {})
        if not all(callable(fn) for fn in self.approved_tools.values()):
            raise ValueError('Approved tools must be code-side callables')
        self._lock = threading.RLock()
        self._cache = {}
        self._version = -1
        with self._connect() as conn:
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS capability_entries (
                    kind TEXT NOT NULL, scope TEXT NOT NULL, id TEXT NOT NULL,
                    payload TEXT NOT NULL, PRIMARY KEY(kind, scope, id));
                CREATE TABLE IF NOT EXISTS capability_version (
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1), version INTEGER NOT NULL);
                INSERT OR IGNORE INTO capability_version VALUES (1, 0);
            ''')

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=10)
        try:
            conn.execute('PRAGMA synchronous=FULL')
            with conn:
                yield conn
        finally:
            conn.close()

    def _key(self, kind, entry_id, scope):
        if kind not in self.KINDS:
            raise ValueError('Unknown registry kind')
        if not isinstance(entry_id, str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,199}', entry_id):
            raise ValueError('Invalid registry ID')
        if kind == 'agent' and scope is None:
            raise ValueError('Agent entries require an explicit scope')
        if kind != 'agent' and scope is not None:
            raise ValueError('Skills and tool metadata are application-global')
        return kind, scope.key() if scope else '', entry_id

    def _validate(self, kind, entry_id, payload):
        if not isinstance(payload, dict):
            raise ValueError('Registry payload must be a JSON object')
        # Metadata is never a mechanism for registering runtime code.
        forbidden = {'code', 'script', 'module', 'callable', 'command', 'exec', 'python', 'shell'}
        def inspect(value):
            if isinstance(value, dict):
                if forbidden & value.keys():
                    raise ValueError('Executable code fields are forbidden')
                for item in value.values():
                    inspect(item)
            elif isinstance(value, list):
                for item in value:
                    inspect(item)
        inspect(payload)
        serialized = json.dumps(payload, allow_nan=False, sort_keys=True)
        if len(serialized.encode()) > 200_000:
            raise ValueError('Registry payload exceeds 200 KB')
        if kind == 'tool' and entry_id not in self.approved_tools:
            raise ValueError('Tool has no approved code-side binding')
        if kind == 'agent':
            names = payload.get('tool_names', payload.get('tools', []))
            if not isinstance(names, list) or any(name not in self.approved_tools for name in names):
                raise ValueError('Agent requests an unapproved tool')
        return serialized

    def register(self, kind, entry_id, payload, scope: Scope | None = None):
        key = self._key(kind, entry_id, scope)
        serialized = self._validate(kind, entry_id, payload)
        with self._lock:
            with self._connect() as conn:
                conn.execute('BEGIN IMMEDIATE')
                conn.execute('INSERT INTO capability_entries VALUES (?,?,?,?) ON CONFLICT(kind,scope,id) DO UPDATE SET payload=excluded.payload', (*key, serialized))
                conn.execute('UPDATE capability_version SET version=version+1 WHERE singleton=1')
                version = conn.execute('SELECT version FROM capability_version').fetchone()[0]
                conn.commit()  # Failure leaves cache unchanged.
            self._cache.clear()
            self._version = version
            self._cache[key] = json.loads(serialized)
        return json.loads(serialized)

    def _refresh(self, conn):
        version = conn.execute('SELECT version FROM capability_version').fetchone()[0]
        if version != self._version:
            self._cache.clear()
            self._version = version

    def get(self, kind, entry_id, scope: Scope | None = None):
        key = self._key(kind, entry_id, scope)
        with self._lock, self._connect() as conn:
            conn.execute('BEGIN')
            self._refresh(conn)
            if key not in self._cache:
                row = conn.execute('SELECT payload FROM capability_entries WHERE kind=? AND scope=? AND id=?', key).fetchone()
                self._cache[key] = json.loads(row[0]) if row else None
            return copy.deepcopy(self._cache[key])

    def list(self, kind, scope: Scope | None = None):
        key = self._key(kind, 'list', scope)
        with self._lock, self._connect() as conn:
            conn.execute('BEGIN')
            self._refresh(conn)
            rows = conn.execute('SELECT id,payload FROM capability_entries WHERE kind=? AND scope=? ORDER BY id', key[:2]).fetchall()
            return [{**json.loads(raw), 'id': entry_id} for entry_id, raw in rows]

    def search(self, kind, query, scope: Scope | None = None, limit=12):
        terms = set(re.findall(r'[a-z0-9]+', query.lower())) - {'the', 'a', 'and', 'for', 'to', 'of'}
        ranked = []
        for record in self.list(kind, scope):
            text = ' '.join(str(record.get(field, '')) for field in ('id', 'name', 'description', 'goal', 'initial_objective', 'skill_ids', 'skills'))
            words = set(re.findall(r'[a-z0-9]+', text.lower()))
            score = len(terms & words)
            if score:
                ranked.append((score, record['id'], record))
        return [record for _, _, record in sorted(ranked, key=lambda r: (-r[0], r[1]))[:max(1, min(int(limit), 100))]]

    def delete(self, kind, entry_id, scope: Scope | None = None):
        key = self._key(kind, entry_id, scope)
        with self._lock:
            with self._connect() as conn:
                conn.execute('BEGIN IMMEDIATE')
                cursor = conn.execute('DELETE FROM capability_entries WHERE kind=? AND scope=? AND id=?', key)
                conn.execute('UPDATE capability_version SET version=version+1 WHERE singleton=1')
                conn.commit()
            self._cache.clear()
            self._version = -1
            return bool(cursor.rowcount)

    def bind_tools(self, names, policy_allowed):
        if not set(names) <= set(policy_allowed):
            raise ValueError('Requested tools exceed the current policy')
        if any(name not in self.approved_tools or self.get('tool', name) is None for name in names):
            raise ValueError('Tool is not registered and approved')
        return [self.approved_tools[name] for name in names]

    def bootstrap(self, scope: Scope | None = None):
        """Index verified downloaded skill metadata and existing approved manifests.

        Local generic manifests become scoped agent templates only when a scope
        is provided; no cross-user agent entries are implicitly visible.
        """
        from finance_common.skills import inventory
        for entry_id, skill in inventory().items():
            payload = {key: skill[key] for key in ('name', 'description', 'url', 'license', 'sha256', 'local_path')}
            if self.get('skill', entry_id) != payload:
                self.register('skill', entry_id, payload)
        for name, fn in self.approved_tools.items():
            payload = {'name': name, 'description': (fn.__doc__ or '').strip()}
            if self.get('tool', name) != payload:
                self.register('tool', name, payload)
        if scope:
            from dynamic_router.catalog import agents
            for name, spec in agents().items():
                payload = {key: value for key, value in spec.items() if key != 'instruction'}
                if set(payload['tools']) <= self.approved_tools.keys() and self.get('agent', name, scope) is None:
                    self.register('agent', name, payload, scope)
        return {kind: len(self.list(kind, scope if kind == 'agent' else None)) for kind in self.KINDS if kind != 'agent' or scope is not None}


def get_registry(path=None, approved_tools=None):
    """Construct an instance using local approved functions, never persisted code."""
    import os
    if approved_tools is None:
        from finance_common.calculations import get_finance_case, analyze_finance_case
        from finance_common.skills import search_finance_skills, load_finance_skill, read_finance_resource
        from dynamic_router.tools import TOOLS
        approved_tools = {**TOOLS, **{fn.__name__: fn for fn in (
            get_finance_case, analyze_finance_case, search_finance_skills,
            load_finance_skill, read_finance_resource)}}
    selected = path or os.getenv('CAPABILITY_REGISTRY_DB') or Path(__file__).resolve().parents[1] / '.adk' / 'capabilities.sqlite3'
    return RegistryService(selected, approved_tools)
