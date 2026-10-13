"""Copy legacy custom memories into MemoryLayer, leaving the source database intact."""
import json
import sqlite3
from pathlib import Path
from memory_layer.service import MemoryWrite,MemoryService
from memory_layer.scitrera import MemoryLayerRepository

def main():
    source=Path('.adk/custom-memory.sqlite3')
    if not source.exists():
        print('No legacy memory database to migrate');return
    service=MemoryService(MemoryLayerRepository())
    with sqlite3.connect(f'file:{source.resolve()}?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        rows=db.execute('SELECT * FROM custom_memory_v2').fetchall()
    counts={'migrated':0,'already_present':0}
    for row in rows:
        existing=service.retrieve(row['app'],row['user'],'',50,row['kind'],row['session_id'])
        if any(item['key']==row['key'] for item in existing):
            counts['already_present']+=1;continue
        memory=MemoryWrite(key=row['key'],text=row['text'],metadata={**json.loads(row['metadata']),'migration_source':'custom-memory.sqlite3','original_updated_at':row['updated_at']},kind=row['kind'],session_id=row['session_id'])
        service.store(row['app'],row['user'],memory);counts['migrated']+=1
    Path('outputs/memorylayer-migration.json').write_text(json.dumps(counts,indent=2))
    print('Legacy migration:',counts,'; source unchanged')

if __name__=='__main__':main()
