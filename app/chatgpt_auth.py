"""Official ChatGPT plan OAuth for this local app; never reads another app's tokens."""
import base64
import hashlib
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ISSUER = 'https://auth.openai.com'
RESOURCE = 'https://api.openai.com/v1'
SCOPES = 'openid profile email offline_access resource.invoke chatgpt.tokens.use.direct'
TERMINAL_REFRESH = {'invalid_grant','invalid_refresh_token','token_expired','refresh_token_expired',
                    'refresh_token_invalidated','refresh_token_reused'}


class AuthError(Exception):
    """Only curated/sanitized messages may leave this module."""


def private_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    temp = path.with_name(path.name + '.' + secrets.token_hex(6) + '.tmp')
    fd = os.open(str(temp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(value, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
        os.chmod(path, 0o600)
    finally:
        if temp.exists():
            temp.unlink()


def safe_request(url, data=None, token=None):
    headers = {'Accept':'application/json'}
    if data is not None:
        data = urllib.parse.urlencode(data).encode()
        headers['Content-Type'] = 'application/x-www-form-urlencoded'
    if token:
        headers['Authorization'] = 'Bearer ' + token
    request = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            raw = response.read(1024 * 1024)
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        code = ''
        try:
            body = json.loads(exc.read(16000))
            error = body.get('error')
            candidate = error.get('code','') if isinstance(error,dict) else error
            if isinstance(candidate,str) and candidate.replace('_','').isalnum():
                code = candidate[:100]
        except (ValueError, AttributeError):
            pass
        raise AuthError('HTTP ' + str(exc.code) + (' / ' + code if code else '')) from None
    except (urllib.error.URLError, OSError, ValueError):
        raise AuthError('连接 OpenAI 失败，请稍后重试。') from None


class ChatGPTAuth:
    def __init__(self, directory, request=None, verify=None, clock=None):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.directory, 0o700)
        self.path = self.directory / 'chatgpt-accounts.json'
        self.lock = threading.RLock()
        self.pending = {}
        self.request = request or safe_request
        self.verify_override = verify
        self.clock = clock or time.time
        self.discovery_cache = None
        self.last_error = None
        try:
            self.data = json.loads(self.path.read_text()) if self.path.exists() else {}
        except (ValueError, OSError):
            raise AuthError('本地 ChatGPT 连接配置无法读取，请检查授权文件。') from None
        self.data.setdefault('host_id','urn:uuid:' + str(__import__('uuid').uuid4()))
        self.data.setdefault('accounts',{})
        self.data.setdefault('active',None)
        self.save()

    def save(self):
        private_json(self.path, self.data)

    def discovery(self):
        if self.discovery_cache is None:
            d = self.request(ISSUER + '/.well-known/openid-configuration')
            if d.get('issuer') != ISSUER:
                raise AuthError('OpenAI 身份服务返回了不匹配的 issuer。')
            for key in ('authorization_endpoint','token_endpoint','jwks_uri','revocation_endpoint'):
                value = d.get(key,'')
                u = urllib.parse.urlsplit(value)
                if u.scheme != 'https' or u.netloc != 'auth.openai.com':
                    raise AuthError('OpenAI 身份服务配置异常。')
            self.discovery_cache = d
        return self.discovery_cache

    def available(self):
        if self.verify_override:
            return True
        try:
            import jwt
            import cryptography
            return True
        except ImportError:
            return False

    def active(self):
        return self.data['accounts'].get(self.data['active'])

    def status(self):
        with self.lock:
            account = self.active()
            return {'available':self.available(), 'connected':bool(account and account.get('access_token')),
                    'plan_enabled':bool(account and account.get('access_token') and
                                        'chatgpt.tokens.use.direct' in account.get('scopes',[])),
                    'active_id':self.data['active'], 'error':self.last_error,
                    'accounts':[{'id':key,'label':a.get('email') or 'ChatGPT account',
                                 'registration':a['client_id'][-8:],
                                 'connected':bool(a.get('access_token'))}
                                for key,a in self.data['accounts'].items()]}

    def begin(self, base_url, browser_binding, account_id=None, enable_plan=False):
        with self.lock:
            if not self.available():
                raise AuthError('ChatGPT 授权需要安装 requirements-chatgpt.txt 中的依赖。')
            if account_id and account_id not in self.data['accounts']:
                raise AuthError('找不到选中的 ChatGPT 账号。')
            account = self.data['accounts'].get(account_id)
            u = urllib.parse.urlsplit(base_url)
            if u.scheme != 'http' or u.hostname != '127.0.0.1' or not u.port:
                raise AuthError('授权回调必须使用 127.0.0.1 本地地址。')
            state, verifier, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(64), secrets.token_urlsafe(32)
            callback = base_url + '/auth/chatgpt/callback'
            params = {'client_id':account['client_id'] if account else 'dynamic_agent_client',
                      'ext_agent_host_id':self.data['host_id'], 'response_type':'code',
                      'redirect_uri':callback,'scope':SCOPES,'resource':RESOURCE,
                      'state':state,'nonce':nonce,'code_challenge_method':'S256',
                      'code_challenge':base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')}
            if account:
                if account.get('id_token'):
                    params['id_token_hint'] = account['id_token']
                if account.get('email'):
                    params['login_hint'] = account['email']
                if enable_plan:
                    params['prompt'] = 'consent'
            else:
                params['agent_name_hint'] = 'IT Companion'
            url = self.discovery()['authorization_endpoint'] + '?' + urllib.parse.urlencode(params)
            self.pending = {k:v for k,v in self.pending.items() if self.clock()-v['created']<600}
            # A new login from the same browser invalidates that browser's prior pending login.
            self.pending = {k:v for k,v in self.pending.items() if v['binding']!=browser_binding}
            self.pending[state] = {'created':self.clock(),'binding':browser_binding,'verifier':verifier,
                                   'nonce':nonce,'callback':callback,'account_id':account_id,
                                   'client_id':account['client_id'] if account else None,'url':url}
            self.last_error = None
            return state

    def authorize_url(self, state, binding):
        with self.lock:
            tx = self.pending.get(state)
            if not tx or tx['binding'] != binding or self.clock()-tx['created']>600:
                raise AuthError('登录请求已失效，请重新开始。')
            return tx['url']

    def validate_identity(self, encoded, client, nonce=None):
        if self.verify_override:
            return self.verify_override(encoded, client, nonce)
        try:
            import jwt
            jwks = jwt.PyJWKClient(self.discovery()['jwks_uri'], timeout=15)
            key = jwks.get_signing_key_from_jwt(encoded)
            claims = jwt.decode(encoded,key.key,algorithms=['RS256'],issuer=ISSUER,audience=client,
                                leeway=5,options={'require':['sub','exp','iat','iss','aud']})
            if not isinstance(claims.get('sub'),str) or not claims['sub']:
                raise ValueError('Missing subject')
            if nonce is not None and not secrets.compare_digest(str(claims.get('nonce','')),nonce):
                raise ValueError('Nonce mismatch')
            return claims
        except AuthError:
            raise
        except Exception:
            raise AuthError('OpenAI 身份令牌验证失败，未保存此次授权。') from None

    def complete(self, query, binding):
        state = query.get('state','')
        with self.lock:
            tx = self.pending.get(state)
            if (not tx or not binding or not secrets.compare_digest(tx['binding'],binding)
                    or self.clock()-tx['created']>600):
                raise AuthError('授权状态不匹配或已过期，请重新登录。')
            self.pending.pop(state)  # one-use, including unsuccessful callbacks
            if query.get('error'):
                raise AuthError('没有完成授权。你可以重新登录，或继续使用 API Key。')
            code = query.get('code')
            client = query.get('client_id') or tx['client_id']
            if not code or not client or client=='dynamic_agent_client' or not client.startswith('oaiapp_'):
                raise AuthError('授权没有返回有效的注册信息。')
            if tx['client_id'] and tx['client_id']!=client:
                raise AuthError('授权返回的客户端与选中账号不一致。')
            tokens = self.request(self.discovery()['token_endpoint'], data={
                'grant_type':'authorization_code','client_id':client,'code':code,
                'code_verifier':tx['verifier'],'redirect_uri':tx['callback'],'resource':RESOURCE})
            claims = self.validate_identity(tokens.get('id_token',''),client,tx['nonce'])
            old = self.data['accounts'].get(tx['account_id'])
            if old and claims['sub']!=old['subject']:
                raise AuthError('登录账号与选中的账号不一致，未替换原来的授权。')
            if tokens.get('token_type','').lower()!='bearer' or not tokens.get('access_token'):
                raise AuthError('授权没有返回可用的访问凭证。')
            key = hashlib.sha256((ISSUER+'|'+client+'|'+claims['sub']).encode()).hexdigest()[:24]
            self.data['accounts'][key] = {'client_id':client,'subject':claims['sub'],'issuer':ISSUER,
                'email':claims.get('email',''),'ext_agent_host_id':self.data['host_id'],
                'id_token':tokens['id_token'],'access_token':tokens['access_token'],
                'refresh_token':tokens.get('refresh_token',''),'token_type':'Bearer',
                'scopes':tokens.get('scope','').split(),
                'expires_at':self.clock()+float(tokens.get('expires_in',3600)),
                'models':[], 'selected_model':None}
            self.data['active'] = key
            self.save()
            self.last_error = None
            return self.status()

    def credentials(self, account_id=None):
        with self.lock:
            key = account_id or self.data['active']
            a = self.data['accounts'].get(key)
            if not a or not a.get('access_token'):
                raise AuthError('请先使用 ChatGPT 登录。')
            if 'chatgpt.tokens.use.direct' not in a.get('scopes',[]):
                raise AuthError('已登录，但没有授权使用 ChatGPT 额度，请点击“授权使用订阅额度”。')
            if a['expires_at'] > self.clock()+60:
                return dict(a)
            if not a.get('refresh_token'):
                raise AuthError('登录已过期，请重新登录。')
            try:
                tokens = self.request(self.discovery()['token_endpoint'],data={
                    'grant_type':'refresh_token','client_id':a['client_id'],
                    'refresh_token':a['refresh_token'],'resource':RESOURCE})
            except AuthError as exc:
                if any(code in str(exc) for code in TERMINAL_REFRESH):
                    for field in ('access_token','refresh_token','id_token'):
                        a.pop(field,None)
                    self.save()
                    raise AuthError('ChatGPT 授权已失效，请重新登录。') from None
                raise
            if not tokens.get('access_token'):
                raise AuthError('刷新授权失败，请稍后重试。')
            if tokens.get('id_token'):
                identity = self.validate_identity(tokens['id_token'],a['client_id'])
                if identity['sub']!=a['subject']:
                    raise AuthError('刷新授权时账号不匹配。')
                a['id_token']=tokens['id_token']
            a.update(access_token=tokens['access_token'],
                     refresh_token=tokens.get('refresh_token',a['refresh_token']),
                     expires_at=self.clock()+float(tokens.get('expires_in',3600)),
                     scopes=tokens.get('scope',' '.join(a['scopes'])).split())
            self.save()
            if 'chatgpt.tokens.use.direct' not in a['scopes']:
                raise AuthError('ChatGPT 额度授权已取消，请重新授权。')
            return dict(a)

    def models(self, account_id=None):
        key = account_id or self.data['active']
        credentials = self.credentials(key)
        body = self.request(RESOURCE+'/models',token=credentials['access_token'])
        models = [{'id':m['slug'],'name':m.get('display_name',m['slug'])}
                  for m in body.get('models',[]) if m.get('visibility')=='list' and isinstance(m.get('slug'),str)]
        if not models:
            raise AuthError('这个账号没有返回可用模型，请检查订阅和授权。')
        with self.lock:
            account = self.data['accounts'][key]
            account['models'] = models
            if account.get('selected_model') not in {m['id'] for m in models}:
                account['selected_model'] = models[0]['id']
            self.save()
        return models

    def select(self, account_id, model=None):
        with self.lock:
            if account_id not in self.data['accounts']:
                raise AuthError('账号不存在。')
            a = self.data['accounts'][account_id]
            if model is not None:
                if model not in {m['id'] for m in a.get('models',[])}:
                    raise AuthError('请选择当前账号返回的模型。')
                a['selected_model'] = model
            self.data['active'] = account_id
            self.save()

    def disconnect(self):
        with self.lock:
            a = self.active()
            confirmed = True
            if a and a.get('refresh_token'):
                try:
                    self.request(self.discovery()['revocation_endpoint'],data={
                        'token':a['refresh_token'],'token_type_hint':'refresh_token','client_id':a['client_id']})
                except AuthError:
                    confirmed = False
            if a:
                for field in ('access_token','refresh_token','id_token'):
                    a.pop(field,None)
                a['models'] = []
                a['selected_model'] = None
            self.save()
            return {'remote_revocation_confirmed':confirmed}
