"""Read-only local development registry inspection; identities are demo partitions."""
from fastapi import APIRouter
from . import Scope
from finance_common.runtime import capability_registry
router=APIRouter(prefix='/api/registry',tags=['capability registry'])

@router.get('/{app_name}/{user_id}/{session_id}')
def inspect_registry(app_name:str,user_id:str,session_id:str):
    registry=capability_registry()
    scope=Scope(app_name,user_id,session_id)
    return {'agents':registry.list('agent',scope),'skills':registry.list('skill'),
            'tools':registry.list('tool'),'cache':'write-through, SQLite commit before publication; version-based invalidation'}
