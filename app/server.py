"""Loopback HTTP app with separate demo, API Key and ChatGPT OAuth channels."""
import argparse
import json
import os
import secrets
import threading
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

from .agent import Agent
from .chatgpt_auth import AuthError, ChatGPTAuth
from .provider import ChatGPTProvider, ResponsesProvider
from .store import Store
from .tools import DATA, LABS

ROOT = Path(__file__).resolve().parents[1]


class AppServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, agent, auth=None):
        super().__init__(address, Handler)
        self.agent = agent
        self.auth = auth
        self.session_lock = threading.RLock()

    def for_session(self, session):
        mode = session['mode']
        if mode=='chatgpt':
            if not self.auth:
                raise AuthError('ChatGPT 授权功能未启用。')
            provider = ChatGPTProvider(self.auth,session.get('chatgpt_account'),session.get('model'))
            return Agent(self.agent.store,mode,provider)
        return Agent(self.agent.store,mode,ResponsesProvider())

    def config(self):
        return {'mode':self.agent.mode,'api_key_configured':bool(os.environ.get('OPENAI_API_KEY') and os.environ.get('OPENAI_MODEL')),
                'api_key_model':os.environ.get('OPENAI_MODEL',''),
                'chatgpt':self.auth.status() if self.auth else {'available':False,'connected':False,'plan_enabled':False,'accounts':[]},
                'snapshot_time':DATA['snapshot_time'],
                'users':[{'id':k,**v} for k,v in DATA['users'].items()],'labs':sorted(LABS)}


class Handler(BaseHTTPRequestHandler):
    server_version = 'LocalITSupport/1.1'

    def log_message(self, format, *args):
        pass  # Never log callback query strings, credentials, body or cookies.

    def headers_out(self, code, content_type='application/json; charset=utf-8', cookie=None, extra=None):
        self.send_response(code)
        self.send_header('Content-Type',content_type)
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Content-Security-Policy',"default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        if cookie:
            self.send_header('Set-Cookie',f'session={cookie}; HttpOnly; SameSite=Strict; Path=/')
        for key,value in (extra or {}).items():
            self.send_header(key,value)
        self.end_headers()

    def send_json(self, code, body, cookie=None, extra=None):
        self.headers_out(code,cookie=cookie,extra=extra)
        self.wfile.write(json.dumps(body,ensure_ascii=False).encode())

    def cookies(self):
        c = SimpleCookie()
        try:
            c.load(self.headers.get('Cookie',''))
        except Exception:
            return SimpleCookie()
        return c

    def current(self):
        cookies = self.cookies()
        key = cookies['session'].value if 'session' in cookies else ''
        return self.server.agent.store.get(key)

    def auth_binding(self):
        c = self.cookies()
        return c['oauth_binding'].value if 'oauth_binding' in c else ''

    def valid_host(self):
        return self.headers.get('Host') in {'127.0.0.1:'+str(self.server.server_port),'localhost:'+str(self.server.server_port)}

    def redirect(self, location, clear_binding=False):
        extra = {'Location':location}
        if clear_binding:
            extra['Set-Cookie']='oauth_binding=; HttpOnly; SameSite=Lax; Path=/auth/chatgpt/; Max-Age=0'
        self.headers_out(303,extra=extra)

    def do_GET(self):
        if not self.valid_host():
            return self.send_json(403,{'error':'Invalid local Host'})
        path = urlsplit(self.path).path
        if path.startswith('/auth/chatgpt/'):
            if not self.server.auth:
                return self.send_json(400,{'error':'ChatGPT 授权未启用。'})
            try:
                query = parse_qs(urlsplit(self.path).query,keep_blank_values=True)
                if any(len(v)!=1 for v in query.values()):
                    raise AuthError('授权参数重复，请重新登录。')
                query = {k:v[0] for k,v in query.items()}
                if path=='/auth/chatgpt/authorize':
                    url = self.server.auth.authorize_url(query.get('state',''),self.auth_binding())
                    return self.redirect(url)
                if path=='/auth/chatgpt/callback':
                    self.server.auth.complete(query,self.auth_binding())
                    return self.redirect('/?chatgpt=connected',True)
                return self.send_json(404,{'error':'Not found'})
            except AuthError as exc:
                self.server.auth.last_error=str(exc)
                return self.redirect('/?chatgpt=error',True)
            except Exception:
                self.server.auth.last_error='授权回调未完成，请重新登录。原有连接没有被替换。'
                return self.redirect('/?chatgpt=error',True)
        if path=='/api/config':
            return self.send_json(200,self.server.config())
        if path=='/api/session':
            s = self.current()
            return self.send_json(200,self.server.agent.public(s) if s else None)
        if path=='/api/handoff':
            s = self.current()
            if not s or not s['handoff']:
                return self.send_json(404,{'error':'No local handoff'})
            return self.send_json(200,s['handoff'])
        if path in {'/','/style.css','/app.js'}:
            file = ROOT/'web'/('index.html' if path=='/' else path[1:])
            mime = {'.html':'text/html; charset=utf-8','.css':'text/css; charset=utf-8','.js':'text/javascript; charset=utf-8'}[file.suffix]
            self.headers_out(200,mime)
            self.wfile.write(file.read_bytes())
            return
        self.send_json(404,{'error':'Not found'})

    def do_POST(self):
        origin = self.headers.get('Origin')
        if (not self.valid_host() or self.headers.get('X-Local-App')!='it-support' or
            (origin and origin not in {'http://127.0.0.1:'+str(self.server.server_port),
                                       'http://localhost:'+str(self.server.server_port)})):
            # Drain a small rejected body so closing the socket does not reset the JSON response.
            try:
                length = int(self.headers.get('Content-Length','0'))
                if 0 < length <= 16000:
                    self.connection.settimeout(3)
                    self.rfile.read(length)
            except (ValueError, OSError):
                pass
            return self.send_json(403,{'error':'Local origin and app header required'})
        try:
            length = int(self.headers.get('Content-Length','0'))
            if not 0<length<=16000:
                raise ValueError('Invalid request size')
            body = json.loads(self.rfile.read(length))
            if not isinstance(body,dict):
                raise ValueError('Expected JSON object')
            if self.path.startswith('/api/chatgpt/'):
                auth = self.server.auth
                if not auth:
                    raise AuthError('ChatGPT 授权未启用。')
                if self.path=='/api/chatgpt/start':
                    if self.headers.get('Host')!='127.0.0.1:'+str(self.server.server_port):
                        raise AuthError('请从 http://127.0.0.1:'+str(self.server.server_port)+' 打开应用再授权。')
                    binding = secrets.token_urlsafe(32)
                    state = auth.begin('http://127.0.0.1:'+str(self.server.server_port),binding,
                                       body.get('account_id'),bool(body.get('enable_plan')))
                    return self.send_json(200,{'redirect':'/auth/chatgpt/authorize?'+urlencode({'state':state})},extra={
                        'Set-Cookie':'oauth_binding='+binding+'; HttpOnly; SameSite=Lax; Path=/auth/chatgpt/; Max-Age=600'})
                if self.path=='/api/chatgpt/models':
                    models = auth.models(body.get('account_id'))
                    return self.send_json(200,{'models':models,'active_id':auth.data['active']})
                if self.path=='/api/chatgpt/select':
                    auth.select(body.get('account_id'),body.get('model'))
                    return self.send_json(200,auth.status())
                if self.path=='/api/chatgpt/disconnect':
                    return self.send_json(200,auth.disconnect())
                return self.send_json(404,{'error':'Not found'})
            with self.server.session_lock:
                if self.path=='/api/session':
                    mode = body.get('mode',self.server.agent.mode)
                    if mode not in {'demo','openai','chatgpt'}:
                        raise ValueError('Unknown connection mode')
                    if mode=='openai' and not self.server.config()['api_key_configured']:
                        raise AuthError('API Key 方式仍然可用，请先在服务器配置 OPENAI_API_KEY 和 OPENAI_MODEL。')
                    s = Agent(self.server.agent.store,mode).new(body.get('user_id','e001'),body.get('lab','normal'))
                    if mode=='chatgpt':
                        if not self.server.auth:
                            raise AuthError('ChatGPT 授权未启用。')
                        account = self.server.auth.active()
                        s['chatgpt_account'] = self.server.auth.data['active']
                        s['model'] = account.get('selected_model') if account else None
                    elif mode=='openai':
                        s['model'] = os.environ.get('OPENAI_MODEL')
                    self.server.agent.store.save(s)
                    return self.send_json(201,self.server.agent.public(s),s['id'])
                if self.path=='/api/chat':
                    s = self.current()
                    if not s:
                        return self.send_json(401,{'error':'Start a session first'})
                    if s['mode']=='chatgpt':
                        if not self.server.auth:
                            raise AuthError('ChatGPT 授权未启用。')
                        if not s.get('chatgpt_account') or not s.get('model'):
                            raise AuthError('请先完成 ChatGPT 授权、选择模型，再开始新会话。')
                        self.server.auth.credentials(s['chatgpt_account'])
                    message = body.get('message')
                    if not isinstance(message,str):
                        raise ValueError('Message must be a string')
                    agent = self.server.for_session(s)
                    s = agent.turn(s,message)
                    return self.send_json(200,agent.public(s))
            return self.send_json(404,{'error':'Not found'})
        except AuthError as exc:
            return self.send_json(400,{'error':str(exc)[:250]})
        except (ValueError,TypeError) as exc:
            return self.send_json(400,{'error':str(exc)[:150]})
        except Exception:
            return self.send_json(500,{'error':'Unexpected local error. No credentials were returned.'})


def main():
    parser = argparse.ArgumentParser(description='Local synthetic IT support agent')
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--mode',choices=['demo','openai','chatgpt'],default=os.environ.get('AGENT_MODE','demo'))
    parser.add_argument('--db',default=str(ROOT/'runtime/support.sqlite3'))
    parser.add_argument('--auth-dir',default=str(ROOT/'runtime/oauth'))
    args = parser.parse_args()
    if args.mode=='openai' and (not os.environ.get('OPENAI_API_KEY') or not os.environ.get('OPENAI_MODEL')):
        parser.error('openai mode requires OPENAI_API_KEY and OPENAI_MODEL. No automatic fallback.')
    store = Store(args.db)
    auth = ChatGPTAuth(args.auth_dir)
    server = AppServer(('127.0.0.1',args.port),Agent(store,args.mode),auth)
    print(f'IT support: http://127.0.0.1:{server.server_port} | mode={args.mode} | synthetic data only',flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        store.close()


if __name__=='__main__':
    main()
