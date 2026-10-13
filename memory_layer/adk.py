"""ADK BaseMemoryService adapter for custom database memory, usable with Runner."""
import asyncio
from google.adk.memory.base_memory_service import BaseMemoryService, MemoryEntry, SearchMemoryResponse
from google.genai import types
from .service import MemoryWrite, get_memory_service

class CustomDatabaseMemoryService(BaseMemoryService):
    def __init__(self, service=None):
        self.service = service or get_memory_service()

    async def add_session_to_memory(self, session):
        await self.add_events_to_memory(app_name=session.app_name, user_id=session.user_id,
                                       events=session.events, session_id=session.id)

    async def add_events_to_memory(self, *, app_name, user_id, events, session_id=None, custom_metadata=None):
        import hashlib
        for event in events:
            content = event.content
            if not content:
                continue
            text = '\n'.join(p.text for p in (content.parts or []) if p.text and not p.thought)
            if not text.strip():
                continue
            digest = hashlib.sha256(f'{session_id}:{event.id}'.encode()).hexdigest()
            memory = MemoryWrite(key='event_'+digest, text=text[:20000],
                                 metadata={**(custom_metadata or {}), 'session_id': session_id, 'author': event.author})
            await asyncio.to_thread(self.service.store, app_name, user_id, memory)

    async def add_memory(self, *, app_name, user_id, memories, custom_metadata=None):
        import hashlib
        for entry in memories:
            text = '\n'.join(p.text for p in (entry.content.parts or []) if p.text and not p.thought)
            if not text.strip():
                continue
            key = 'entry_' + hashlib.sha256((entry.id or text).encode()).hexdigest()
            memory = MemoryWrite(key=key, text=text, metadata={**(custom_metadata or {}), **entry.custom_metadata, 'author': entry.author})
            await asyncio.to_thread(self.service.store, app_name, user_id, memory)

    async def search_memory(self, *, app_name, user_id, query):
        rows = await asyncio.to_thread(self.service.retrieve, app_name, user_id, query)
        return SearchMemoryResponse(memories=[MemoryEntry(id=row['key'],
            content=types.Content(role='user', parts=[types.Part(text=row['text'])]),
            timestamp=row['updated_at'], author=row['metadata'].get('author'), custom_metadata=row['metadata']) for row in rows])
