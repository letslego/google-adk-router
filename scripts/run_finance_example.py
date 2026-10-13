"""Execute the goal designer first, then either routing example against local ADK."""
import argparse
import json
from pathlib import Path
import uuid
import httpx

ROOT = Path(__file__).resolve().parents[1]
PROMPTS = {
    'goal': 'Your goal is to create and save a complex acquisition-underwriting task for the supplied fictional Northstar case using at least five complementary downloaded finance skills. Include valuation, downside debt stress, leveraged returns, due diligence, and a final committee memo. Define dependencies, measurable acceptance checks, missing evidence, and completion gates. Get the case, discover and load skills, start the goal, and finalize the task artifact.',
    'dynamic': 'Assess the fictional Northstar acquisition using dynamic routing. Discover downloaded skills, create and route to at least three new specialist agents covering valuation, credit/leveraged returns, and due diligence/investment committee synthesis. Use at least four distinct skills. Use actual base and downside numerical observations, pass prior findings downstream, and produce a concise evidence-backed analytical memo with breached gates and missing evidence. Do not make a real approval.',
    'react': 'Use your explicit ReAct loop to assess the fictional Northstar acquisition. Observe case inputs, discover complementary downloaded finance skills, calculate base and downside, route to at least two new specialist agents, and return a concise evidence-backed analytical memo. Highlight breached leverage/coverage/liquidity gates, valuation and sponsor returns, missing evidence, and limitations. This is a synthetic analytical demonstration, not an actual credit approval.',
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=PROMPTS)
    parser.add_argument('--url', default='http://127.0.0.1:8000')
    args = parser.parse_args()
    app = {'goal': 'finance_goal', 'dynamic': 'finance_dynamic', 'react': 'finance_react'}[args.mode]
    sid = 'finance_' + args.mode + '_' + uuid.uuid4().hex
    path = f'/apps/{app}/users/finance_demo/sessions/{sid}'
    with httpx.Client(timeout=600) as client:
        response = client.post(args.url + path, json={})
        response.raise_for_status()
        prompt = PROMPTS[args.mode]
        task_path = ROOT / 'examples/finance/generated-task.json'
        if args.mode != 'goal' and task_path.exists():
            prompt += '\nUse this skill-grounded task as the analytical objective: ' + json.dumps(json.loads(task_path.read_text())['task'])
        response = client.post(args.url + '/run', json={'app_name': app, 'user_id': 'finance_demo', 'session_id': sid,
                                                      'new_message': {'role': 'user', 'parts': [{'text': prompt}]}})
        response.raise_for_status()
        events = response.json()
        response = client.get(args.url + path)
        response.raise_for_status()
        session = response.json()
    state = session['state']
    if any(e.get('errorCode') or e.get('errorMessage') for e in events):
        raise SystemExit('Execution failed; inspect the saved session in ADK.')
    if args.mode == 'goal':
        assert state.get('finance_goal', {}).get('status') == 'complete', 'Goal did not finalize'
        artifact = ROOT / 'outputs/finance_tasks' / (state['finance_goal']['id'] + '.json')
        task_path.write_text(artifact.read_text())
        count = len({sid for s in state['finance_task']['stages'] for sid in s['skill_ids']})
        print(f'Goal complete: {len(state["finance_task"]["stages"])} stages, {count} skills')
    elif args.mode == 'dynamic':
        assert len(state.get('finance_agents', {})) >= 3, 'Expected >=3 specialist agents'
        assert len(state.get('finance_observations', [])) >= 3, 'Expected >=3 specialist results'
        assert len(state.get('finance_loaded_skills', [])) >= 4, 'Expected >=4 skills'
        print('Dynamic routing verified:', ', '.join(state['finance_agents']))
    else:
        assert state.get('react_status') == 'complete', 'ReAct did not reach completion gate'
        trace = state.get('react_observations', [])
        assert {o['observation']['scenario'] for o in trace if o['action'] == 'calculate'} == {'base', 'downside'}, 'Expected both scenarios'
        print('ReAct verified:', ' -> '.join(o['action'] for o in trace))
    output = ROOT / 'outputs/finance_runs' / (sid + '.json')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({'mode': args.mode, 'app': app, 'session_id': sid,
                                 'events': events, 'state': state}, indent=2))
    print('Saved run:', output)
    print(f'Open: {args.url}/dev-ui/?app={app}&userId=finance_demo&session={sid}')


if __name__ == '__main__':
    main()
