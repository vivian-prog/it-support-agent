"""Bounded orchestration + deterministic action gates + evidence-based rendering."""
import json
import re
import secrets
import time
from datetime import datetime, timezone

from . import tools
from .provider import ProviderError, ResponsesProvider


def now():
    return datetime.now(timezone.utc).isoformat()


def redact(text):
    # Defense in depth, not a complete DLP system. Avoid collecting secrets at all.
    text = re.sub(r'\bsk-[A-Za-z0-9_-]+', '[REDACTED]', text)
    text = re.sub(r'(?i)\b(?:bearer)\s+\S+', 'Bearer [REDACTED]', text)
    text = re.sub(r'(?i)((?:password|passwd|token|api[_ -]?key|验证码|密码|恢复码|令牌)\s*[:：=]\s*)[^\s,，;；]+', r'\1[REDACTED]', text)
    return re.sub(r'\b\d{6}\b', '[REDACTED-CODE]', text)


def contains(text, terms):
    return any(t in text for t in terms)


def explicit_success(text):
    """Accept explicit recovery reports, rejecting negated, hypothetical or mixed failure reports."""
    t = text.strip().lower().rstrip('。.!！')
    if contains(t, ['如果','假如','假设','要是','会不会','是不是','能否','是否','应该','可能','也许',
                    '希望','还没试','还没有试','还没做','还没有做','？','?',
                    'hopefully','maybe','should work','if it','if the']):
        return False
    if re.search(r'还没(?:有)?(?:解决|恢复|正常)|尚未|没有(?:解决|恢复)|未(?:解决|恢复)|'
                 r'(?:还是|仍然|仍会|仍在|依然|还会|又).{0,12}(?:断线|掉线|断开|断了|掉了|打不开|不行|失败)|'
                 r"\b(?:not|isn't|hasn't|haven't|can't|cannot|unable)\b|"
                 r'\bstill.{0,24}(?:drop|disconnect|fail|broken|unavailable)',t):
        return False
    if t in {'好了','解决了','已经解决了','可以了','恢复了','恢复正常了','已恢复','问题解决了',
             '可以访问了','不再断线了','能登录了','resolved','it works','it works now','fixed','working now'}:
        return True
    return bool(re.search(r'已经正常了|恢复正常|已经恢复|已恢复|已经解决|问题解决了|'
                          r'能打开了|可以访问了|能登录了|不再断线|没再(?:掉|断线|掉线)|'
                          r'\b(?:working now|works now|back to normal|everything is working|'
                          r'problem is fixed|issue is resolved|can now access)\b',t))


def explicit_topic_switch(text):
    t = text.lower()
    return contains(t, ['换个问题','另一个问题','另外','先不说','先放下','不说这个','不是断线',
                        '不是掉线','其实是','顺便','different issue','another problem','instead'])


def classify(text):
    t = text.lower()
    if contains(t, ['jenkins','tableau','pipeline','数据管道','salesforce','printer','打印机','硬盘','蓝屏']):
        return 'other'
    if contains(t, ['申请','开通','grant access','request access','need access','access to snowflake','production database','生产数据库','授予权限','给我权限','我要权限','需要权限']):
        return 'access'
    if contains(t, ['okta','password','密码','mfa','account','账号','sign in','log in','login']):
        return 'account'
    if contains(t, ['内网','internal','grafana','dns']):
        return 'internal' if not contains(t, ['断','disconnect','掉线']) else 'vpn'
    if contains(t, ['vpn','断线','掉线','disconnect']):
        return 'vpn'
    return None


def detect_location(text):
    t = text.lower()
    if contains(t, ['remote','at home','home wi','hotspot','远程','在家','家里','热点']):
        return 'remote'
    if contains(t, ['in the office','at the office','在公司','办公室办公']):
        return 'office'
    return None


def detect_symptom(text):
    t = text.lower()
    if contains(t, ['断线','掉线','断开','disconnect','一直断','老是断']):
        return 'disconnect'
    if contains(t, ['打不开','内网','internal','dns','已连接']):
        return 'connected_no_access'
    if contains(t, ['登录','login','log in','sign in','password','密码']):
        return 'login_failure'
    return None


class Agent:
    def __init__(self, store, mode='demo', provider=None):
        if mode not in {'demo','openai','chatgpt'}:
            raise ValueError('Unknown agent mode')
        self.store, self.mode = store, mode
        self.provider = provider or ResponsesProvider()

    def new(self, user_id='e001', lab='normal'):
        if user_id not in tools.DATA['users'] or lab not in tools.LABS:
            raise ValueError('Unknown synthetic user or lab')
        s = {'id':secrets.token_urlsafe(32),'created_at':now(),'user_id':user_id,'lab':lab,
             'mode':self.mode,'phase':'clarifying','issue':None,'location':'unknown','symptom':'unknown',
             'messages':[],'trace':[],'ledger':{},'attempts':[],'handoff':None,'last':None,
             'metrics':{'turns':0,'tool_calls':0,'model_calls':0,'input_tokens':0,'output_tokens':0},
             'api_items':[]}
        self.store.save(s)
        return s

    def record(self, s, name, args, result, elapsed, ok=True, source="rule"):
        event = {'at':now(),'turn':s['metrics']['turns'],'tool':name,'args':args,'source':source,
                 'result':result,'ok':ok,'duration_ms':round(elapsed * 1000, 2)}
        s['trace'].append(event)
        s['metrics']['tool_calls'] += 1
        self.store.event(s['id'], event)
        return result

    def call(self, s, name, args, source="rule"):
        start = time.monotonic()
        try:
            if not isinstance(args, dict):
                raise tools.ToolError('Arguments must be an object')
            if name == 'set_context':
                domains = {'issue':{'vpn','internal','account','access','other'},
                           'location':{'remote','office','unknown'},
                           'symptom':{'disconnect','connected_no_access','login_failure','unknown'}}
                if set(args) != set(domains) or any(v not in domains[k] for k,v in args.items()):
                    raise tools.ToolError('Invalid context schema')
                # A model cannot erase an issue that the code has classified as high risk.
                if s['issue'] in {'access','other'}:
                    args = dict(args, issue=s['issue'])
                if s['issue'] != args['issue']:
                    s['ledger'] = {}
                    s['attempts'] = []
                for k,v in args.items():
                    if v != 'unknown' or s.get(k) in {None,'unknown'}:
                        s[k] = v
                result = {k:s[k] for k in domains}
            else:
                expected = {'get_profile':set(),'check_status':{'service'},'search_kb':{'issue','query'},
                            'search_history':{'issue'},'check_policy':{'action'}}
                if name not in expected or set(args) != expected[name]:
                    raise tools.ToolError('Unauthorized tool or invalid argument schema')
                if any(not isinstance(v,str) or len(v)>1500 for v in args.values()):
                    raise tools.ToolError('Invalid tool argument')
                result = tools.execute(name, args, s)
                key = name + (':' + args['service'] if name == 'check_status' else
                              ':' + args['action'] if name == 'check_policy' else '')
                s['ledger'][key] = {'ok':True,'result':result}
            return self.record(s, name, args, result, time.monotonic()-start,source=source)
        except tools.ToolError as exc:
            result = {'error':str(exc)}
            if name == 'check_status':
                s['ledger']['check_status:' + str((args or {}).get('service',''))] = {'ok':False,'result':result}
            return self.record(s,name,args,result,time.monotonic()-start,False,source=source)

    def evidence(self, s):
        ids = []
        for entry in s['ledger'].values():
            if not entry['ok']:
                continue
            r = entry['result']
            if 'id' in r:
                ids.append(r['id'])
            ids += [a['id'] for a in r.get('articles',[])]
            ids += [a['id'] for a in r.get('cases',[])]
        return list(dict.fromkeys(ids))

    def escalate(self, s, reason):
        if not s['handoff']:
            s['handoff'] = {'id':'LOCAL-' + secrets.token_hex(4).upper(),'created_at':now(),
                'delivery':'local_only_not_sent','employee_id':s['user_id'],
                'employee':tools.DATA['users'][s['user_id']]['name'],
                'priority':'urgent' if contains(' '.join(m['content'].lower() for m in s['messages'] if m['role']=='user'),
                                               ['urgent','30分钟','30 minutes','紧急','客户会议']) else 'normal',
                'reason':reason,'issue':s['issue'],'reported_location':s['location'],'reported_symptom':s['symptom'],
                'evidence_ids':self.evidence(s),'attempts':list(s['attempts']),
                'unresolved':['Root cause is not verified. / 根因尚未确认。',
                              'Human should verify current health, employee identity and requested permission scope. / 人工需核实实时状态、身份及权限范围。'],
                'conversation':list(s['messages']),
                'investigation':list(s['trace'])}
        s['phase'] = 'escalated'
        return {'decision':'escalate','text':reason + '\n问题和排查记录已经整理好了，还没发给 IT。你可以下载后交给支持人员。',
                'evidence_ids':self.evidence(s),'confidence':'需要人工确认'}

    def ask(self, s, question):
        questions = {
            'problem':'先说一下具体哪里用不了、大概什么时候开始的。比如 VPN 会断线，或者账号登录不上。别发密码和验证码。',
            'location':'再告诉我一下，你现在是在家远程办公，还是在公司。',
            'symptom':'再说一下具体表现，比如连不上、连上后又断了，或者显示已连接但内网打不开。有报错的话，发错误提示就行，注意删掉敏感信息。',
            'feedback':'试完后告诉我结果，比如还会不会断线、内网能不能打开。已经恢复的话，回复“解决了”就行。'}
        if question not in questions:
            question = 'problem'
        s['phase'] = 'awaiting_feedback' if question=='feedback' else 'clarifying'
        return {'decision':'ask','text':questions[question], 'question':question,
                'evidence_ids':self.evidence(s),'confidence':'还需要了解情况'}

    def finish(self, s, proposal):
        decision = proposal.get('decision')
        latest = next((m['content'] for m in reversed(s['messages']) if m['role']=='user'), '')
        if decision == 'resolved':
            if not s['attempts'] or not explicit_success(latest):
                return self.ask(s,'feedback' if s['attempts'] else 'problem')
            s['phase'] = 'resolved'
            return {'decision':'resolved','text':'收到，你确认已经恢复，这次就先记为已解决。后面再遇到问题，可以开一个新会话。',
                    'evidence_ids':self.evidence(s),'confidence':'你已确认恢复'}
        if decision == 'escalate':
            # Render model-selected categories, never arbitrary model-generated instructions.
            reasons = {'uncertain':'现有信息还不足以判断，先交给 IT 继续排查。',
                       'unresolved':'试过之后还没恢复，需要 IT 继续排查。',
                       'policy':'这个操作需要人工确认或审批，我这边不能直接处理。',
                       'out_of_scope':'这个问题目前处理不了，需要 IT 接着看。',
                       'human_requested':'收到，这次转人工处理。'}
            return self.escalate(s,reasons.get(proposal.get('reason'),'现在还没确认解决，需要 IT 继续看。'))
        if decision == 'ask':
            return self.ask(s, proposal.get('question','problem'))
        if decision != 'guide':
            return self.escalate(s,'暂时没找到可靠的下一步，先交给 IT 处理。')
        # Hard gates apply equally to deterministic and LLM planners.
        if s['issue'] in {'access','other',None}:
            return self.escalate(s,'这个请求需要审批，或者需要 IT 进一步处理。')
        if s['location']=='unknown':
            return self.ask(s,'location')
        if s['symptom']=='unknown':
            return self.ask(s,'symptom')
        profile_entry = s['ledger'].get('get_profile',{})
        if not profile_entry.get('ok'):
            return self.escalate(s,'还没查到你的设备和权限信息，暂时不能继续判断。')
        if s['issue'] in {'vpn','internal'} and not profile_entry['result']['vpn_access']:
            return self.escalate(s,'查到的员工资料里没有 VPN 权限，需要先由 IT 确认和审批。')
        service = 'identity' if s['issue']=='account' else 'vpn'
        status = s['ledger'].get('check_status:' + service,{})
        if not status.get('ok') or not status['result'].get('fresh'):
            return self.escalate(s,'没查到最新的服务状态，现在还不能确定是不是服务出了问题。')
        if status['result']['health'] != 'operational':
            return self.escalate(s,'查到 VPN 服务正在出故障。这种情况需要负责团队处理，先不用反复改本地设置。')
        articles = s['ledger'].get('search_kb',{}).get('result',{}).get('articles',[])
        if len({a['action'] for a in articles}) > 1:
            return self.escalate(s,'查到的两份资料说法不一致，暂时不能确定该按哪份操作，需要 IT 核对。')
        article = next((a for a in articles if a['id']==proposal.get('article_id')),None)
        if not article or article.get('retired') or article.get('issue') != s['issue']:
            return self.escalate(s,'没有找到适合这个问题的排查资料，先交给 IT 看。')
        if article not in tools.DATA['articles']:
            return self.escalate(s,'这份操作说明还没有审核过，暂时不能照着做。')
        if profile_entry['result']['device'] not in article.get('platforms',[]):
            return self.escalate(s,'这份操作说明不适合你的设备，需要 IT 再确认。')
        if article['action']=='network_isolation' and s['location']!='remote':
            return self.escalate(s,'这个方法只适合远程办公。在公司遇到的网络问题，需要 IT 继续排查。')
        p = s['ledger'].get('check_policy:' + article['action'],{})
        if not p.get('ok') or p['result'].get('disposition')!='allowed':
            return self.escalate(s,'还没确认这个操作是否允许，暂时不能继续。')
        if article['id'] in [a['article_id'] for a in s['attempts']]:
            return self.escalate(s,'这一步已经试过了，再重复也帮不上忙，交给 IT 继续看。')
        if len(s['attempts']) >= tools.DATA['policy']['max_guidance_attempts']:
            return self.escalate(s,'目前能做的排查已经试过了，需要 IT 继续处理。')
        attempt = {'article_id':article['id'],'action':article['action'],'steps':article['steps'],
                   'outcome':'awaiting_user_feedback','turn':s['metrics']['turns']}
        s['attempts'].append(attempt)
        s['phase'] = 'awaiting_feedback'
        return {'decision':'guide','text':'先按下面的方法试一下，看看问题有没有变化。现在还不能确定原因，试完把结果告诉我。',
                'steps':article['steps'],'article_id':article['id'],'success_criteria':article['success'],
                'evidence_ids':self.evidence(s),'confidence':'等你试完反馈'}

    def demo_plan(self, s, text):
        if s['attempts']:
            return {'decision':'resolved'} if explicit_success(text) else {'decision':'escalate','reason':'unresolved'}
        issue = s['issue']
        if not issue:
            return {'decision':'ask','question':'problem'}
        self.call(s,'get_profile',{})
        if issue=='access':
            self.call(s,'check_policy',{'action':'grant_access'})
            return {'decision':'escalate','reason':'policy'}
        if issue=='other':
            return {'decision':'escalate','reason':'out_of_scope'}
        if s['location']=='unknown':
            return {'decision':'ask','question':'location'}
        if s['symptom']=='unknown':
            return {'decision':'ask','question':'symptom'}
        self.call(s,'check_status',{'service':'identity' if issue=='account' else 'vpn'})
        kb = self.call(s,'search_kb',{'issue':issue,'query':text})
        self.call(s,'search_history',{'issue':issue})
        articles = kb.get('articles',[])
        if articles:
            self.call(s,'check_policy',{'action':articles[0]['action']})
        return {'decision':'guide','article_id':articles[0]['id'] if articles else ''}

    def model_plan(self, s):
        s['api_items'].append({'role':'user','content':s['messages'][-1]['content']})
        # Store model protocol items for within-session multi-turn reasoning, including reasoning items.
        items = s['api_items']
        calls = 0
        started = time.monotonic()
        for _ in range(8):
            if time.monotonic()-started > 55:
                raise ProviderError('Model turn time budget exceeded')
            context = {'phase':s['phase'],'issue':s['issue'],'location':s['location'],'symptom':s['symptom'],
                       'attempts':s['attempts'],'verified_evidence_ids':self.evidence(s),
                       'synthetic_snapshot_clock':tools.DATA['snapshot_time']}
            # Fresh server state cannot be overridden by untrusted conversation text.
            s['metrics']['model_calls'] += 1
            try:
                response = self.provider.request([{'role':'developer','content':'Server state: ' + json.dumps(context,ensure_ascii=False)}] + items)
            except ProviderError as exc:
                s['metrics']['transport_retries'] = s['metrics'].get('transport_retries',0)+getattr(exc,'transport_retries',0)
                raise
            retries = response.get('_transport_retries',0)
            s['metrics']['transport_retries'] = s['metrics'].get('transport_retries',0)+retries
            if retries:
                event = {'at':now(),'turn':s['metrics']['turns'],'tool':'model_transport_retry',
                         'source':'transport','ok':True,'duration_ms':0,
                         'result':{'retries':retries,'error_classes':response.get('_transport_retry_errors',[])}}
                s['trace'].append(event)
                self.store.event(s['id'],event)
            usage = response.get('usage',{})
            for key in ('input_tokens','output_tokens'):
                s['metrics'][key] += usage.get(key,0)
            outputs = response.get('output',[])
            if not isinstance(outputs,list):
                raise ProviderError('Malformed model output')
            items.extend(outputs)
            function_calls = [o for o in outputs if o.get('type')=='function_call']
            if not function_calls:
                raise ProviderError('Model did not return a decision tool call')
            final = None
            for c in function_calls:
                if c.get('namespace') not in {None,'it_support'}:
                    raise ProviderError('Model requested an unauthorized tool namespace')
                calls += 1
                if calls > 10:
                    raise ProviderError('Tool-call budget exceeded')
                try:
                    args = json.loads(c.get('arguments','{}'))
                except (ValueError, TypeError):
                    args = None
                if c.get('name')=='finish':
                    if not isinstance(args,dict) or set(args)!={'decision','question','article_id','reason'}:
                        result = {'error':'Invalid finish schema'}
                    else:
                        final = args
                        result = {'proposal_received':True,'note':'The server will validate and render the actual reply.'}
                    self.record(s,'finish',args,result,0,not bool(result.get('error')),source='model')
                else:
                    result = self.call(s,c.get('name'),args,source='model')
                items.append({'type':'function_call_output','call_id':c['call_id'],
                              'output':json.dumps(result,ensure_ascii=False)})
            if final is not None:
                return final
        raise ProviderError('Model-step budget exceeded')

    def turn(self, s, text):
        start = time.monotonic()
        if s['phase'] in {'resolved','escalated'}:
            return s
        text = redact(text.strip())
        if not text or len(text)>2000:
            raise ValueError('Message must be 1–2000 characters')
        if s['metrics']['turns'] >= 20:
            result = self.escalate(s,'这次已经排查了比较久，需要 IT 接着处理。')
        else:
            s['metrics']['turns'] += 1
            s['messages'].append({'role':'user','content':text,'at':now()})
            latest_issue = classify(text)
            # Feedback about an internal page after a VPN check belongs to the same issue.
            # Strong access/out-of-scope requests still switch immediately and clear authorization evidence.
            related_network_feedback = (s['phase']=='awaiting_feedback'
                and s['issue'] in {'vpn','internal'} and latest_issue in {'vpn','internal'}
                and not explicit_topic_switch(text))
            if latest_issue and latest_issue != s['issue'] and not related_network_feedback:
                s.update(issue=latest_issue,ledger={},attempts=[],symptom='unknown')
            location, symptom = detect_location(text), detect_symptom(text)
            if location:
                s['location'] = location
            if symptom:
                s['symptom'] = symptom
            if s['attempts']:
                s['attempts'][-1]['outcome'] = 'user_confirmed_resolved' if explicit_success(text) else 'user_feedback: ' + text
            t = text.lower()
            locked = contains(t,['锁定','locked','unlock','解锁'])
            dangerous = contains(t,['关闭防火墙','关闭杀毒','关闭终端防护','disable firewall','disable security','bypass mfa','绕过mfa'])
            human = contains(t,['转人工','找人工','human','speak to it','真人'])
            if human:
                result = self.escalate(s,'收到，这次转人工处理。')
            elif dangerous or locked:
                self.call(s,'check_policy',{'action':'disable_security' if dangerous else 'unlock_account'})
                result = self.escalate(s,'修改安全设置、解锁账号这类操作，需要 IT 核实后处理。')
            elif s['issue'] in {'access','other'}:
                result = self.finish(s,self.demo_plan(s,text))
            elif s['attempts'] and explicit_success(text):
                result = self.finish(s,{'decision':'resolved'})
            else:
                try:
                    proposal = self.model_plan(s) if self.mode in {'openai','chatgpt'} else self.demo_plan(s,text)
                    result = self.finish(s,proposal)
                    if self.mode in {'openai','chatgpt'}:
                        s['api_items'].append({'role':'assistant','content':json.dumps(result,ensure_ascii=False)})
                except (ProviderError, ValueError, KeyError, TypeError) as exc:
                    # Only sanitized error classes/messages leave the provider layer.
                    message = str(exc) if isinstance(exc,ProviderError) else type(exc).__name__
                    s['trace'].append({'at':now(),'turn':s['metrics']['turns'],'tool':'model_error','ok':False,
                                       'result':{'error':message},'duration_ms':0})
                    result = self.escalate(s,'这次没能完成分析，先交给 IT 继续处理。之前的对话和排查记录都保留了。')
        result['duration_ms'] = round((time.monotonic()-start)*1000,2)
        s['last'] = result
        s['messages'].append({'role':'assistant','content':result['text'],'response':result,'at':now()})
        self.store.save(s)
        return s

    def public(self, s):
        return {k:v for k,v in s.items() if k not in {'id','api_items','ledger'}}
