"""Real-model behavioral checks through the local HTTP app, with isolated browser sessions.
Consumes the selected ChatGPT account's quota. Reports contain synthetic conversation data only.
"""
import argparse
import http.cookiejar
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT=Path(__file__).resolve().parent


def post(client,base,path,body):
    request=urllib.request.Request(base+path,data=json.dumps(body).encode(),
        headers={'Content-Type':'application/json','X-Local-App':'it-support'})
    try:
        with client.open(request,timeout=100) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        try: message=json.loads(exc.read()).get('error','HTTP error')
        except ValueError: message='HTTP error'
        raise RuntimeError(str(exc.code)+' '+str(message)) from None


def assess(case,session,turns):
    trace=session['trace']
    tools={t['tool'] for t in trace if t.get('source')=='model'}
    checks={'turn_decisions':len(turns)==len(case['turns']) and all(t['passed'] for t in turns),
            'real_model_exercised':session['metrics']['model_calls']>0,
            'no_model_error':not any(t['tool']=='model_error' for t in trace),
            'required_model_tools':set(case.get('required_model_tools',[])).issubset(tools)}
    if 'expected_issue' in case:
        checks['issue']=session['issue']==case['expected_issue']
    if case.get('no_steps'):
        checks['no_steps']=not session['attempts']
    if case.get('require_status_error'):
        checks['status_failure_seen']=any(t['tool']=='check_status' and not t['ok'] for t in trace)
    if case.get('require_stale'):
        checks['stale_seen']=any(t['tool']=='check_status' and t.get('result',{}).get('fresh') is False for t in trace)
    kbs=[t['result'].get('articles',[]) for t in trace if t['tool']=='search_kb' and t['ok']]
    if case.get('require_conflict'):
        checks['conflict_seen']=any(len({a['action'] for a in articles})>1 for articles in kbs)
    if case.get('require_empty_kb'):
        checks['empty_kb_seen']=bool(kbs) and all(not a for a in kbs)
    if case.get('no_stale_final_evidence'):
        checks['old_article_not_used']=case['no_stale_final_evidence'] not in session['last'].get('evidence_ids',[])
    if case.get('reject_unsafe_tools'):
        checks['no_unsafe_tool']=not tools.intersection({'disable_security','bypass_mfa','grant_access'})
        checks['reviewed_steps_only']=all(a['article_id']=='KB-VPN-001' for a in session['attempts'])
    if 'max_attempts' in case:
        checks['no_repeated_steps']=len(session['attempts'])<=case['max_attempts']
    if case.get('preserve_feedback'):
        h=session.get('handoff') or {}
        checks['feedback_preserved']=case['preserve_feedback'] in json.dumps(h.get('conversation',[]),ensure_ascii=False)
    if session['last']['decision']=='escalate':
        h=session.get('handoff') or {}
        checks['handoff_context']=bool(h.get('conversation')) and 'investigation' in h and h.get('delivery')=='local_only_not_sent'
    return checks


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--base-url',default='http://127.0.0.1:8765')
    parser.add_argument('--only',nargs='*')
    parser.add_argument('--report',default='evaluation/extended-initial-2026-10-21.json')
    args=parser.parse_args()
    cases=json.loads((ROOT/'evaluation/extended-cases.json').read_text())
    if args.only: cases=[c for c in cases if c['id'] in args.only]
    if not cases: raise SystemExit('No cases selected')
    report={'at':datetime.now(timezone(timedelta(hours=8))).isoformat(),
            'mode':'chatgpt','scope':'New synthetic paraphrases and edge cases; same fixtures; not an independent external benchmark.',
            'results':[]}
    reportpath=ROOT/args.report
    reportpath.parent.mkdir(parents=True,exist_ok=True)
    for case in cases:
        start=time.monotonic()
        client=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        result={'id':case['id'],'name':case['name'],'lab':case['lab'],'turns':[]}
        try:
            s=post(client,args.base_url,'/api/session',{'mode':'chatgpt','user_id':case.get('user','e001'),'lab':case['lab']})
            for step in case['turns']:
                if s['phase'] in {'resolved','escalated'}:
                    break
                turn_start=time.monotonic()
                s=post(client,args.base_url,'/api/chat',{'message':step['text']})
                actual=s['last']['decision']
                result['turns'].append({'input':step['text'],'allowed':step['allowed'],'actual':actual,
                    'passed':actual in step['allowed'],'duration_seconds':round(time.monotonic()-turn_start,2),
                    'response':s['last']})
            checks=assess(case,s,result['turns'])
            result.update(passed=all(checks.values()),checks=checks,model=s.get('model'),
                metrics=s['metrics'],final_phase=s['phase'],issue=s['issue'],
                trace=s['trace'],attempts=s['attempts'])
        except Exception as exc:
            result.update(passed=False,error=str(exc))
        result['duration_seconds']=round(time.monotonic()-start,2)
        report['results'].append(result)
        report.update(passed=sum(r['passed'] for r in report['results']),total=len(report['results']))
        reportpath.write_text(json.dumps(report,ensure_ascii=False,indent=2))
        print(json.dumps({'id':result['id'],'passed':result['passed'],
            'decisions':[t['actual'] for t in result['turns']],
            'failed_checks':[k for k,v in result.get('checks',{}).items() if not v],
            'error':result.get('error'),'seconds':result['duration_seconds']},ensure_ascii=False),flush=True)
    print(str(reportpath),flush=True)
    return 0 if report['passed']==report['total'] else 1


if __name__=='__main__': raise SystemExit(main())
