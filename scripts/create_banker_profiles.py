"""Create the two requested banker personas in persistent MemLayer profile memory."""
import json
from pathlib import Path
from memory_layer.service import MemoryService,MemoryWrite
from memory_layer.memlayer import MemLayerRepository
ROOT=Path(__file__).resolve().parents[1]

def main():
    profiles=json.loads((ROOT/'examples/personas/banker-profiles.json').read_text())
    service=MemoryService(MemLayerRepository())
    for name,profile in profiles.items():
        existing=service.retrieve('finance_registry',profile['user_id'],'',50,'profile')
        if any(row['key']=='banker_profile' for row in existing):
            print(profile['display_name']+': already created');continue
        service.store('finance_registry',profile['user_id'],MemoryWrite(key='banker_profile',text=json.dumps(profile),kind='profile',metadata={'persona':name,'source':'user_requested_profile'}))
        print(profile['display_name']+': created in persistent profile memory')
if __name__=='__main__':main()
