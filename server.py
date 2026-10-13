"""Local ADK API and task-to-agent chat on the same origin."""
import os
from pathlib import Path
import uvicorn
from fastapi.responses import FileResponse
from google.adk.cli.fast_api import get_fast_api_app

ROOT = Path(__file__).resolve().parent
app = get_fast_api_app(agents_dir=str(ROOT), web=True, extra_plugins=['memory_layer.plugin.PersistentMemoryPlugin'], host='127.0.0.1', port=int(os.getenv('PORT', '8000')), max_llm_calls=24)

@app.get('/chat', include_in_schema=False)
def chat():
    return FileResponse(ROOT / 'web/chat.html')

@app.get('/api/prompts', include_in_schema=False)
def prompt_library():
    import json
    return json.loads((ROOT / 'examples/prompts/library.json').read_text())

# ADK's development UI mounts a catch-all static route. Put this page ahead of it.
app.router.routes.insert(0, app.router.routes.pop())
app.router.routes.insert(0, app.router.routes.pop())

from memory_layer.api import router as memory_router
count = len(app.router.routes)
app.include_router(memory_router)
from capability_registry.api import router as registry_router
app.include_router(registry_router)
new_routes = app.router.routes[count:]
del app.router.routes[count:]
app.router.routes[0:0] = new_routes

if __name__ == '__main__':
    uvicorn.run(app, host='127.0.0.1', port=int(os.getenv('PORT', '8000')))
