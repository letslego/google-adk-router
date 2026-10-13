"""Run ordered prompt scenarios against local ADK and verify observable state/tool evidence."""
import argparse
import json
import uuid
from pathlib import Path
import httpx
ROOT=Path(__file__).resolve().parents[1]
LIBRARY=ROOT/'examples/prompts/library.json'

def tool_names(events):
    return {part['functionCall']['name'] for event in events for part in event.get('content',{}).get('parts',[]) if part.get('functionCall')}

def verify(check,state,events,previous_agents,client,url,app,user,session):
    kind=check['type']
    if kind=='route':
        assert state.get('registry_route',{}).get('route')==check['value'], 'Expected registry route '+check['value']
    elif kind=='same_agents':
        assert set(state.get('finance_agents',{}))==previous_agents, 'Agent registry changed on reuse'
    elif kind=='parallel_plan':
        plan=state.get('registry_plan',{})
        assert plan.get('status')=='complete', 'Plan incomplete'
        assert any(len(batch)>1 for batch in plan.get('batches',[])), 'No parallel batch'
        assert plan['batches'][-1]==['synthesis'], 'Synthesis must follow independent stages'
    elif kind=='restricted_profile':
        assert state.get('finance_policy_profile')==check['value'], 'Incorrect policy profile'
        for record in state.get('finance_agents',{}).values():
            spec=record.get('spec',record)
            assert not {'get_finance_case','analyze_finance_case'} & set(spec.get('tool_names',[])), 'Forbidden numerical tools equipped'
    elif kind=='operational_audit':
        response=client.get(f'{url}/api/memory/{app}/{user}',params={'kind':'operational','limit':50});response.raise_for_status()
        assert any(row.get('metadata',{}).get('tool')==check['tool'] and row['metadata'].get('source')=='tool_execution' for row in response.json()['memories']), 'Operational tool audit missing'
    elif kind=='memory_tool_called':
        assert check['value'] in tool_names(events), 'Expected memory tool was not called'
    elif kind in {'memory_contains','memory_absent'}:
        params={'kind':check['kind'],'limit':50,'session_id':session if check['kind'] in {'working','short_term'} else ''}
        response=client.get(f'{url}/api/memory/{app}/{user}',params=params);response.raise_for_status()
        found=[row for row in response.json()['memories'] if row['key']==check['key']]
        if kind=='memory_absent':assert not found, 'Session memory leaked'
        else:assert found and check['text'].lower() in found[0]['text'].lower(), 'Expected stored memory missing'
    else:raise ValueError('Unknown check '+kind)

def run_scenario(scenario,url,run_id):
    app=scenario['app'];user='promptlib_'+scenario['persona']+'_'+run_id
    session=None;previous_agents=set();results=[]
    with httpx.Client(timeout=600) as client:
        for step in scenario['steps']:
            if session is None or step.get('new_session'):
                session='promptlib_'+uuid.uuid4().hex
                response=client.post(f'{url}/apps/{app}/users/{user}/sessions/{session}',json={});response.raise_for_status()
            response=client.post(url+'/run',json={'app_name':app,'user_id':user,'session_id':session,'new_message':{'role':'user','parts':[{'text':step['prompt']}]}});response.raise_for_status()
            events=response.json()
            assert not any(e.get('errorCode') or e.get('errorMessage') for e in events), 'ADK execution error'
            response=client.get(f'{url}/apps/{app}/users/{user}/sessions/{session}');response.raise_for_status();state=response.json()['state']
            for check in step['checks']:verify(check,state,events,previous_agents,client,url,app,user,session)
            previous_agents=set(state.get('finance_agents',{}))
            results.append({'step':step['id'],'status':'pass','session':session,'route':state.get('registry_route'),
                'agents':sorted(previous_agents),'parallel_batches':state.get('registry_plan',{}).get('batches'),
                'observed_tools':sorted(tool_names(events))})
            print(scenario['id']+'/'+step['id']+': pass',flush=True)
    return {'scenario':scenario['id'],'persona':scenario['persona'],'user':user,'steps':results}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--scenario',action='append',help='Repeat to select scenarios; default runs all')
    parser.add_argument('--list',action='store_true')
    parser.add_argument('--url',default='http://127.0.0.1:8000')
    args=parser.parse_args();scenarios=json.loads(LIBRARY.read_text())['scenarios']
    if args.list:
        for item in scenarios:print(item['id']+' — '+item['title'])
        return
    if args.scenario:
        unknown=set(args.scenario)-{s['id'] for s in scenarios}
        if unknown:parser.error('Unknown scenarios: '+', '.join(sorted(unknown)))
        scenarios=[s for s in scenarios if s['id'] in args.scenario]
    run_id=uuid.uuid4().hex[:10];results=[];failures=[]
    for scenario in scenarios:
        try:results.append(run_scenario(scenario,args.url,run_id))
        except Exception as exc:
            failures.append({'scenario':scenario['id'],'error':str(exc)})
            print(scenario['id']+': FAILED '+str(exc),flush=True)
    output=ROOT/'outputs/prompt_library'/f'{run_id}.json';output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps({'run_id':run_id,'results':results,'failures':failures},indent=2))
    print('Report:',output)
    if failures:raise SystemExit(1)

if __name__=='__main__':main()
