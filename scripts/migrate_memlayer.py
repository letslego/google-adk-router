"""Copy legacy memories into letslego/memlayer without deleting the source database."""
import json,sqlite3
from pathlib import Path
from memory_layer.memlayer import MemLayerRepository
from memory_layer.service import MemoryService,MemoryWrite

def main():
    source=Path('.adk/custom-memory.sqlite3')
    if not source.exists():print('No legacy custom database');return
    service=MemoryService(MemLayerRepository())
    with sqlite3.connect(f'file:{source.resolve()}?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row;rows=db.execute('SELECT * FROM custom_memory_v2').fetchall()
    count=0
    for row in rows:
        existing=service.retrieve(row['app'],row['user'],'',50,row['kind'],row['session_id'])
        if any(r['key']==row['key'] for r in existing):continue
        service.store(row['app'],row['user'],MemoryWrite(key=row['key'],text=row['text'],kind=row['kind'],session_id=row['session_id'],metadata={**json.loads(row['metadata']),'migration_source':'legacy_custom_sqlite','original_updated_at':row['updated_at']}));count+=1
    print('Copied',count,'records; legacy source unchanged')
if __name__=='__main__':main()
