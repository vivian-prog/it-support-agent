"""Reproducible workflow scenarios; --live consumes API tokens for synthetic cases."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from app.agent import Agent
from app.store import Store
ROOT = Path(__file__).resolve().parent


def evaluate(mode='demo', output=None):
    cases = json.loads((ROOT/'evaluation/cases.json').read_text())
    results = []
    for case in cases:
        store=Store(':memory:')
        agent=Agent(store,mode)
        s=agent.new(case.get('user','e001'),case.get('lab','normal'))
        actual=[]
        for text in case['turns']:
            agent.turn(s,text)
            actual.append(s['last']['decision'])
        tools={t['tool'] for t in s['trace']}
        tools_ok=set(case['tools']).issubset(tools)
        handoff_ok=not s['handoff'] or all(k in s['handoff'] for k in ['conversation','investigation','attempts','unresolved','evidence_ids'])
        results.append({'id':case['id'],'passed':actual==case['expected'] and tools_ok and handoff_ok,
                        'expected':case['expected'],'actual':actual,'required_tools_found':tools_ok,
                        'handoff_complete':handoff_ok,'metrics':s['metrics'],'trace':s['trace'],'last':s['last']})
        store.close()
    report={'at':datetime.now(timezone.utc).isoformat(),'mode':mode,
            'scope':'Synthetic workflow regression; does not establish live model quality or generalization.',
            'passed':sum(r['passed'] for r in results),'total':len(results),'results':results}
    path=Path(output) if output else ROOT/'evaluation'/('live-report.json' if mode=='openai' else 'demo-report.json')
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(f"{mode}: {report['passed']}/{report['total']} passed; report={path}")
    for r in results:
        if not r['passed']: print('FAIL',r['id'],'expected=',r['expected'],'actual=',r['actual'])
    return report['passed']==report['total']


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--live',action='store_true')
    p.add_argument('--output')
    args=p.parse_args()
    raise SystemExit(0 if evaluate('openai' if args.live else 'demo',args.output) else 1)
