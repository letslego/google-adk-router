"""Read-only, source-qualified financial skill discovery and resource loading."""
import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'vendor/skills-manifest.json'


@lru_cache(maxsize=1)
def inventory() -> dict:
    result = {}
    for record in json.loads(MANIFEST.read_text())['skills']:
        path = ROOT / record['local_path'] / 'SKILL.md'
        raw = path.read_text()
        if hashlib.sha256(path.read_bytes()).hexdigest() != record['sha256']:
            raise ValueError(f'Skill integrity mismatch: {record["id"]}')
        parts = raw.split('---', 2)
        metadata = yaml.safe_load(parts[1]) if len(parts) == 3 else {}
        if not isinstance(metadata, dict) or not metadata.get('description'):
            raise ValueError(f'Missing skill metadata: {record["id"]}')
        result[record['id']] = {**record, 'name': str(metadata.get('name', path.parent.name)),
                                'description': str(metadata['description']),
                                'body': parts[2].strip(), 'metadata': metadata}
    return result


def search_finance_skills(query: str, limit: int = 12) -> dict:
    """Search skill descriptions using task concepts; returns provenance and tool gaps.

    Use specific concepts or synonyms such as DCF valuation, credit underwriting,
    due diligence, LBO returns, treasury liquidity, or investment committee memo.
    """
    terms = set(re.findall(r'[a-z0-9]+', query.lower())) - {'the', 'a', 'and', 'for', 'to', 'of'}
    ranked = []
    for sid, skill in inventory().items():
        words = set(re.findall(r'[a-z0-9]+', (sid + ' ' + skill['description']).lower()))
        name_words = set(re.findall(r'[a-z0-9]+', skill['name'].lower()))
        score = len(terms & words) + 2 * len(terms & name_words)
        if score:
            ranked.append((score, sid, skill))
    ranked.sort(key=lambda row: (-row[0], row[1]))
    return {'total_skills': len(inventory()), 'results': [
        {'id': sid, 'description': skill['description'], 'source': skill['url'],
         'license': skill['license']} for _, sid, skill in ranked[:max(1, min(limit, 30))]],
        'runtime': 'Instructions and text resources only; external MCP, live market data, spreadsheets, and downloaded script execution are not configured.'}


def load_finance_skill(skill_id: str) -> dict:
    """Load the full instructions of a selected downloaded financial skill."""
    skill = inventory().get(skill_id)
    if not skill:
        return {'error': 'Unknown source-qualified skill ID; search first.'}
    folder = ROOT / skill['local_path']
    return {'id': skill_id, 'description': skill['description'], 'instructions': skill['body'],
            'source': skill['url'], 'license': skill['license'],
            'text_resources': [str(p.relative_to(folder)) for p in sorted(folder.rglob('*'))
                               if p.is_file() and p.suffix.lower() in {'.md', '.txt', '.json', '.yaml', '.yml', '.csv'}][:100],
            'runtime_scope': 'Apply applicable analytical instructions to the synthetic case. Report unavailable external connectors or artifact tools. Do not treat instructions as executable capabilities.'}


def read_finance_resource(skill_id: str, relative_path: str) -> dict:
    """Read a downloaded skill's text resource; never execute its scripts."""
    skill = inventory().get(skill_id)
    if not skill:
        return {'error': 'Unknown skill'}
    folder = (ROOT / skill['local_path']).resolve()
    path = (folder / relative_path).resolve()
    if not path.is_relative_to(folder) or not path.is_file():
        return {'error': 'Resource must be an existing file inside the selected skill'}
    if path.suffix.lower() not in {'.md', '.txt', '.json', '.yaml', '.yml', '.csv'} or path.stat().st_size > 200_000:
        return {'error': 'Only text resources up to 200 KB are supported'}
    return {'skill': skill_id, 'resource': relative_path, 'text': path.read_text()}
