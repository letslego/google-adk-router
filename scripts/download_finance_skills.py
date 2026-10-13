"""Download all skills from the pinned, license-checked source collections.

Uses Codex's skill installer; does not execute any downloaded skill scripts.
"""
import hashlib
import os
import certifi
import json
from pathlib import Path
import subprocess
import sys
import httpx

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = Path(os.getenv('FINANCE_SKILL_INSTALLER', str(Path.home() / '.codex/skills/.system/skill-installer/scripts/install-skill-from-github.py')))


def main():
    records = []
    sources = []
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        for metadata in sorted((ROOT / 'vendor/metadata').glob('*.json')):
            source = json.loads(metadata.read_text())
            if source['truncated'] or source['license'] not in {'MIT', 'Apache-2.0'}:
                raise ValueError('Incomplete inventory or unapproved license')
            repo, sha = source['repo'], source['commit']
            paths = source['skills']
            if repo == 'anthropics/financial-services':
                # Agent plugins duplicate their vertical skill copies. Use canonical sources.
                paths = [p for p in paths if '/vertical-plugins/' in p or '/partner-built/' in p]
            slug = repo.split('/')[0].lower()
            target = ROOT / 'vendor/skills' / slug
            target.mkdir(parents=True, exist_ok=True)
            missing = [str(Path(p).parent) for p in paths if not (target / Path(p).parent.name / 'SKILL.md').exists()]
            if missing:
                subprocess.run([sys.executable, str(INSTALLER), '--repo', repo, '--ref', sha,
                                '--dest', str(target), '--method', 'download', '--path', *missing], check=True,
                               env={**os.environ, 'SSL_CERT_FILE': certifi.where()})
            license_dir = ROOT / 'vendor/licenses' / slug
            license_dir.mkdir(parents=True, exist_ok=True)
            for license_path in source['license_files']:
                r = client.get(f'https://raw.githubusercontent.com/{repo}/{sha}/{license_path}')
                r.raise_for_status()
                dest = license_dir / license_path
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(r.content)
            for skill_path in paths:
                local = target / Path(skill_path).parent.name
                doc = local / 'SKILL.md'
                records.append({'id': slug + '--' + local.name, 'repo': repo, 'commit': sha,
                                'license': source['license'], 'source_path': str(Path(skill_path).parent),
                                'local_path': str(local.relative_to(ROOT)),
                                'sha256': hashlib.sha256(doc.read_bytes()).hexdigest(),
                                'url': f'https://github.com/{repo}/tree/{sha}/{Path(skill_path).parent}'})
            sources.append({'repo': repo, 'commit': sha, 'license': source['license'],
                            'downloaded_skills': len(paths), 'upstream_skill_files': len(source['skills'])})
            print(f'Downloaded {len(paths)} canonical skills from {repo}', flush=True)
    (ROOT / 'vendor/skills-manifest.json').write_text(json.dumps({'scope': 'All canonical skills in the three listed collections; not every skill on the internet.', 'sources': sources, 'skills': records}, indent=2))
    print(f'Catalog ready: {len(records)} source-qualified skills', flush=True)


if __name__ == '__main__':
    main()
