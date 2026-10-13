"""Verify native memory types and persona/session isolation against a running server."""
import json
from pathlib import Path
from memory_layer.service import MemoryService,MemoryWrite
from memory_layer.scitrera import MemoryLayerRepository

PERSONAS=('analyst','risk_reviewer','relationship_manager','auditor')
KINDS=('working','semantic','episodic','procedural')

def main():
    repository=MemoryLayerRepository();service=MemoryService(repository)
    results=[]
    for persona in PERSONAS:
        for kind in KINDS:
            session='native_smoke' if kind=='working' else ''
            text=f'{persona}: {kind} test evidence'
            record=service.store('native_memory_personas',persona,MemoryWrite(key='check_'+kind,text=text,kind=kind,session_id=session))
            assert record['cognitive_type']==kind
            rows=service.retrieve('native_memory_personas',persona,'',50,kind,session)
            assert any(r['text']==text for r in rows)
            assert not service.retrieve('native_memory_personas','unrelated_user','',50,kind,session)
            if kind=='working':
                assert not service.retrieve('native_memory_personas',persona,'',50,kind,'different_session')
            results.append({'persona':persona,'type':kind,'status':'pass'})
    repository.close()
    reopened=MemoryService(MemoryLayerRepository())
    for persona in PERSONAS:
        for kind in KINDS:
            assert reopened.retrieve('native_memory_personas',persona,'',50,kind,'native_smoke' if kind=='working' else '')
    path=Path('outputs/memorylayer-personas.json');path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps({'backend':'Scitrera MemoryLayer server 0.2.0','checks':results,'reopened_client_persistence':'pass'},indent=2))
    print(f'Verified {len(results)} native type/persona combinations and reopened-client persistence')

if __name__=='__main__':main()
