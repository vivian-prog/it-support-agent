'use strict';
let state = null;
let busy = false;
let config = null;
let authState = null;
let authBusy = false;
const $ = id => document.getElementById(id);
const phases = {clarifying:'正在了解问题',awaiting_feedback:'等你反馈',resolved:'已解决',escalated:'待人工处理'};
const issues = {vpn:'VPN 连接',internal:'内网访问',account:'账号登录',access:'权限申请',other:'需要 IT 排查'};
const labNames = {normal:'服务正常',outage:'VPN 服务故障',conflict:'两份资料说法不一致',stale:'服务状态已过期',tool_failure:'服务状态查询失败',no_article:'没有找到相关资料',injection:'资料中混入恶意指令'};
function el(tag, text, className) { const node = document.createElement(tag); if(text !== undefined) node.textContent = text; if(className) node.className=className; return node; }
async function api(path, body) {
  const response = await fetch(path, body === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json','X-Local-App':'it-support'},body:JSON.stringify(body)});
  const data = await response.json();
  if(!response.ok) throw new Error(data.error || '请求失败');
  return data;
}
function setBusy(value) { busy=value; const terminal = state && (['resolved','escalated'].includes(state.phase) || (state.mode==='chatgpt' && (!state.model || !state.chatgpt_account || !authState || !authState.plan_enabled))); $('send').disabled=value || terminal; $('message').disabled=value || terminal; $('human').disabled=value || terminal; $('new-session').disabled=value; $('apply-connection').disabled=value; document.querySelectorAll('[data-prompt]').forEach(b=>b.disabled=value); }
function render() {
  if(!state) return;
  $('employee').textContent = '演示员工 · ' + $('user').selectedOptions[0].textContent;
  $('phase').textContent = phases[state.phase];
  $('mode').textContent = state.mode==='demo'?'演示模式 · 不调用模型':state.mode==='chatgpt'?'ChatGPT 订阅 · '+(state.model || '待授权'):'API Key · '+(state.model || '待配置');
  $('messages').replaceChildren();
  state.messages.forEach((m,i)=>{
    const bubble = el('div',undefined,'bubble ' + m.role);
    bubble.append(el('span',m.role==='user'?'你':'IT 支持','speaker'),el('span',m.content));
    if(m.role==='assistant' && m.response) {
      const last=m.response;
      if(last.steps) { const ol=el('ol'); last.steps.forEach(step=>ol.append(el('li',step))); bubble.append(ol); }
      if(last.evidence_ids.length) bubble.append(el('small','参考资料：' + last.evidence_ids.join(' · '),'source'));
    }
    $('messages').append(bubble);
  });
  $('facts').replaceChildren();
  const pairs=[['问题类型',issues[state.issue] || '待确认'],['当前位置',{remote:'远程',office:'办公室',unknown:'待确认'}[state.location]],['排查方法',state.attempts.length + ' 个'],['当前情况',state.last?state.last.confidence:'还需要了解情况'],['模型请求',state.metrics.model_calls+' 次']];
  for(const [k,v] of pairs) { const p=el('p');p.append(el('span',k),el('strong',v));$('facts').append(p); }
  $('tool-count').textContent=state.metrics.tool_calls;
  if(state.metrics.model_calls) $('trace-details').open=true;
  $('trace').replaceChildren();
  state.trace.forEach(t=>{const d=el('details',undefined,'trace-item' + (t.ok?'':' error'));d.append(el('summary',`${t.source==='model'?'模型调用 · ':''}${t.tool} · ${t.ok?'完成':'失败'} · ${t.duration_ms}ms`),el('pre',JSON.stringify({arguments:t.args,result:t.result},null,2)));$('trace').append(d);});
  $('handoff').classList.toggle('hidden',!state.handoff);$('handoff-note').classList.toggle('hidden',!state.handoff);
  $('starters').classList.toggle('hidden',state.messages.length>0);
  setBusy(busy);
}
async function start() {if(busy) return; setBusy(true);$('error').textContent='';try {state=await api('/api/session',{user_id:$('user').value,lab:$('lab').value,mode:$('connection').value});render();}catch(e){$('error').textContent=e.message;}finally{setBusy(false);}}
async function send(text) {
  if(busy || !text.trim()) return;
  setBusy(true);$('error').textContent='';
  const pending=el('div','稍等，我查一下相关资料。','bubble assistant');$('messages').append(pending);
  try {state=await api('/api/chat',{message:text});$('message').value='';render();}
  catch(e){pending.remove();$('error').textContent='发送失败：' + e.message + '。内容还在输入框里，可以再试一次。';}
  finally {setBusy(false);}
}
$('chat-form').addEventListener('submit',e=>{e.preventDefault();send($('message').value);});
$('message').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();send($('message').value);}});
$('new-session').addEventListener('click',start);
$('human').addEventListener('click',()=>send('请转人工处理。'));
document.querySelectorAll('[data-prompt]').forEach(button=>button.addEventListener('click',()=>send(button.dataset.prompt)));

function connectionView() {
  const choice=$('connection').value;
  $('chatgpt-settings').classList.toggle('hidden',choice!=='chatgpt');
  $('api-key-settings').classList.toggle('hidden',choice!=='openai');
  $('api-key-settings').textContent=config && config.api_key_configured?'服务器已配置 API Key。使用模型：'+config.api_key_model:'API Key 方式已保留。先在服务器配置 OPENAI_API_KEY 和 OPENAI_MODEL，再启用。';
  if(choice==='demo') $('connection-status').textContent='只验证规则流程，不调用大模型。';
  else if(choice==='openai') $('connection-status').textContent='API Key 单独计费，不使用 ChatGPT 订阅。';
  else if(authState) $('connection-status').textContent=authState.error || (authState.plan_enabled?'已授权使用 ChatGPT 额度。选好模型后开始新会话。':authState.connected?'已登录，还没有授权使用订阅额度。':'先登录 ChatGPT，再选择可用模型。');
}
async function authStatus() {
  config=await api('/api/config'); authState=config.chatgpt;
  const accounts=$('chatgpt-account'); const selected=authState.active_id;
  accounts.replaceChildren();
  authState.accounts.forEach(a=>{const o=el('option',a.label+' · '+a.registration);o.value=a.id;accounts.append(o);});
  if(selected) accounts.value=selected;
  const hasAccounts=authState.accounts.length>0;
  ['chatgpt-account','account-label'].forEach(id=>$(id).classList.toggle('hidden',!hasAccounts));
  ['add-account'].forEach(id=>$(id).classList.toggle('hidden',!hasAccounts));
  ['chatgpt-disconnect','usage-link'].forEach(id=>$(id).classList.toggle('hidden',!authState.connected));
  $('enable-plan').classList.toggle('hidden',!authState.connected || authState.plan_enabled);
  $('chatgpt-login').textContent=authState.connected?'重新登录当前账号':'Continue with ChatGPT';
  $('chatgpt-login').disabled=!authState.available;
  ['chatgpt-model','model-label','refresh-models'].forEach(id=>$(id).classList.toggle('hidden',!authState.plan_enabled));
  connectionView();
  if(!authState.available && $('connection').value==='chatgpt') $('connection-status').textContent='需要安装 ChatGPT 授权依赖，请查看 README。';
}
async function models() {
  if(!authState || !authState.plan_enabled) return;
  $('connection-status').textContent='正在获取当前账号可用的模型…';
  try {
    const result=await api('/api/chatgpt/models',{account_id:$('chatgpt-account').value});
    const previous=$('chatgpt-model').value;
    $('chatgpt-model').replaceChildren();
    result.models.forEach(m=>{const o=el('option',m.name);o.value=m.id;$('chatgpt-model').append(o);});
    if(result.models.some(m=>m.id===previous)) $('chatgpt-model').value=previous;
    await api('/api/chatgpt/select',{account_id:$('chatgpt-account').value,model:$('chatgpt-model').value});
    connectionView();
  }catch(e){$('connection-status').textContent='获取模型失败：'+e.message;}
}
async function login(newAccount=false, enablePlan=false) {
  if(authBusy) return;
  authBusy=true; $('chatgpt-login').disabled=true; $('connection-status').textContent='正在打开 OpenAI 登录页面…';
  try {
    const result=await api('/api/chatgpt/start',{account_id:newAccount?null:($('chatgpt-account').value || null),enable_plan:enablePlan});
    window.location.assign(result.redirect);
  } catch(e){$('connection-status').textContent=e.message;authBusy=false;$('chatgpt-login').disabled=false;}
}
$('connection').addEventListener('change',connectionView);
$('apply-connection').addEventListener('click',start);
$('chatgpt-login').addEventListener('click',()=>login());
$('add-account').addEventListener('click',()=>login(true));
$('enable-plan').addEventListener('click',()=>login(false,true));
$('refresh-models').addEventListener('click',models);
$('chatgpt-account').addEventListener('change',async()=>{
  try {await api('/api/chatgpt/select',{account_id:$('chatgpt-account').value}); await authStatus(); await models();}
  catch(e){$('connection-status').textContent=e.message;}
});
$('chatgpt-model').addEventListener('change',async()=>{
  try {await api('/api/chatgpt/select',{account_id:$('chatgpt-account').value,model:$('chatgpt-model').value});$('connection-status').textContent='模型已选好，点下面的按钮开始新会话。';}
  catch(e){$('connection-status').textContent=e.message;}
});
$('chatgpt-disconnect').addEventListener('click',async()=>{
  try {const result=await api('/api/chatgpt/disconnect',{});await authStatus();$('connection-status').textContent=result.remote_revocation_confirmed?'已断开当前账号。':'本地已断开，远程撤销未确认。请到 ChatGPT 设置中检查授权。';}
  catch(e){$('connection-status').textContent=e.message;}
});
(async()=>{
  try {
    config=await api('/api/config');
    config.users.forEach(u=>{const o=el('option',u.name+' · '+u.device);o.value=u.id;$('user').append(o);});
    config.labs.forEach(l=>{const o=el('option',labNames[l]);o.value=l;$('lab').append(o);});
    $('lab').value='normal';
    $('clock').textContent='模拟数据时间：'+config.snapshot_time+'。这里显示的不是实时服务状态。';
    state=await api('/api/session');
    const params=new URLSearchParams(window.location.search);
    const connected=params.get('chatgpt')==='connected';
    $('connection').value=connected || params.get('connection')==='chatgpt'?'chatgpt':state?state.mode:config.mode;
    await authStatus();
    if(authState.plan_enabled) await models();
    if(state && !connected && !params.has('connection')){$('user').value=state.user_id;$('lab').value=state.lab;render();}
    else await start();
    if(params.has('chatgpt') || params.has('connection')) window.history.replaceState({},'', '/');
  }catch(e){$('error').textContent='页面加载失败：'+e.message;}
})();
