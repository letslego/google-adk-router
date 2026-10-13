"""Local development CRUD API. User IDs partition data; they are not authentication."""
from typing import Literal
from fastapi import APIRouter, HTTPException, Query
from .service import MemoryWrite, get_memory_service
router = APIRouter(prefix='/api/memory', tags=['custom memory'])

@router.put('/{app_name}/{user_id}')
def store(app_name: str, user_id: str, memory: MemoryWrite):
    try:
        return get_memory_service().store(app_name, user_id, memory)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

@router.get('/{app_name}/{user_id}')
def retrieve(app_name: str, user_id: str, query: str = Query('', max_length=2000), limit: int = Query(10, ge=1, le=50), kind: Literal['short_term','long_term','episodic','semantic','procedural','working','profile','knowledge','operational'] = 'long_term', session_id: str = ''):
    try:
        return {'memories': get_memory_service().retrieve(app_name, user_id, query, limit, kind, session_id)}
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

@router.delete('/{app_name}/{user_id}/{key}')
def forget(app_name: str, user_id: str, key: str, kind: Literal['short_term','long_term','episodic','semantic','procedural','working','profile','knowledge','operational'] = 'long_term', session_id: str = ''):
    try:
        return {'deleted': get_memory_service().forget(app_name, user_id, key, kind, session_id)}
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
