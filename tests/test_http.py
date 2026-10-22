"""Exercise real HTTP routing, cookie isolation and local-origin boundaries."""
import http.cookiejar
import json
import threading
import unittest
import urllib.error
import urllib.request
from app.agent import Agent
from app.server import AppServer
from app.store import Store


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store=Store(':memory:')
        cls.server=AppServer(('127.0.0.1',0),Agent(cls.store))
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True)
        cls.thread.start()
        cls.url='http://127.0.0.1:' + str(cls.server.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.thread.join()
        cls.server.server_close()
        cls.store.close()

    def setUp(self):
        self.client=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def request(self,path,body=None,headers=None,client=None):
        h={'Content-Type':'application/json','X-Local-App':'it-support'}
        h.update(headers or {})
        req=urllib.request.Request(self.url+path,data=json.dumps(body).encode() if body is not None else None,headers=h)
        try:
            with (client or self.client).open(req,timeout=3) as r:
                return r.status,r.read(),r.headers
        except urllib.error.HTTPError as e:
            return e.code,e.read(),e.headers

    def test_cookie_roundtrip_and_handoff(self):
        status,_,headers=self.request('/api/session',{'user_id':'e001','lab':'normal'})
        self.assertEqual(status,201)
        self.assertIn('HttpOnly',headers['Set-Cookie'])
        status,body,_=self.request('/api/chat',{'message':'我在家远程，VPN 断线。'})
        self.assertEqual(status,200)
        self.assertEqual(json.loads(body)['last']['decision'],'guide')
        self.request('/api/chat',{'message':'还是不行，请转人工。'})
        status,body,_=self.request('/api/handoff')
        self.assertEqual(status,200)
        self.assertEqual(json.loads(body)['delivery'],'local_only_not_sent')
        self.assertIn('response',json.loads(body)['conversation'][1])

    def test_other_client_cannot_read_session(self):
        self.request('/api/session',{})
        other=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        status,body,_=self.request('/api/session',client=other)
        self.assertEqual(status,200)
        self.assertIsNone(json.loads(body))
        self.assertEqual(self.request('/api/chat',{'message':'hello'},client=other)[0],401)

    def test_cross_origin_and_dns_rebinding_blocked(self):
        self.assertEqual(self.request('/api/session',{}, {'Origin':'https://evil.example'})[0],403)
        self.assertEqual(self.request('/api/config',headers={'Host':'evil.example'})[0],403)

    def test_unbounded_and_invalid_input_rejected(self):
        self.request('/api/session',{})
        self.assertEqual(self.request('/api/chat',{'message':'x'*2001})[0],400)
        self.assertEqual(self.request('/api/chat',{'message':{}})[0],400)
        self.assertEqual(self.request('/api/session',{'user_id':'admin'})[0],400)

    def test_static_headers_and_no_path_traversal(self):
        code,body,headers=self.request('/')
        self.assertEqual(code,200)
        self.assertIn('员工 IT 支持'.encode(),body)
        self.assertIn("frame-ancestors 'none'",headers['Content-Security-Policy'])
        self.assertEqual(self.request('/../data/fixtures.json')[0],404)


if __name__=='__main__': unittest.main()
