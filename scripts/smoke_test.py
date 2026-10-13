"""Run live dynamic routing or graph routing against the local ADK server.

This sends example text to the configured model provider and uses API credits.
"""
import argparse
import json
import uuid
import httpx

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--graph', action='store_true')
    parser.add_argument('--url', default='http://127.0.0.1:8000')
    args = parser.parse_args()
    session_id = 'smoke_' + uuid.uuid4().hex
    base = args.url.rstrip('/')
    path = f'/apps/dynamic_router/users/local_smoke/sessions/{session_id}'
    with httpx.Client(timeout=180) as client:
        response = client.post(base + path, json={})
        response.raise_for_status()
        if args.graph:
            prompt = ('Use run_graph with graph_name write_review and path writer, analyst, reviewer. '
                      'Draft a two-sentence announcement that our store now opens at 9am, '
                      'count the words in the draft, and review it for clarity.')
        else:
            prompt = ('Discover capabilities, then delegate to missing agent apology_writer using '
                      'fallback_template writer. Write a two-sentence apology for an order arriving '
                      'three days late. Let delegate create the missing agent automatically; '
                      'do not call create_specialist separately. Return the email.')
        response = client.post(base + '/run', json={
            'app_name': 'dynamic_router', 'user_id': 'local_smoke', 'session_id': session_id,
            'new_message': {'role': 'user', 'parts': [{'text': prompt}]},
        })
        response.raise_for_status()
        events = response.json()
        responses = []
        for event in events:
            if event.get('errorCode') or event.get('errorMessage'):
                raise SystemExit('Provider/agent error; inspect the session in ADK UI.')
            for part in (event.get('content') or {}).get('parts', []):
                if part.get('functionResponse'):
                    responses.append(part['functionResponse'])
        expected = 'run_graph' if args.graph else 'delegate'
        result = next((r['response'] for r in responses if r['name'] == expected), None)
        if not result or 'error' in result:
            raise SystemExit('Expected routing tool did not succeed; inspect ADK UI.')
        if args.graph:
            assert result['path'] == ['writer', 'analyst', 'reviewer']
            assert len(result['outputs']) == 3
        else:
            assert result['agent'] == 'apology_writer' and result['created'] is True
        session = client.get(base + path)
        session.raise_for_status()
        if not args.graph:
            assert 'apology_writer' in session.json()['state']['dynamic_agents']
        print(json.dumps(result, indent=2))
        print(f'Verified {expected}. Session: {session_id}')


if __name__ == "__main__":
    main()
