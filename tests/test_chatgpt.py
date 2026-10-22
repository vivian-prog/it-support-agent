"""OAuth, signature, refresh and SSE contracts using synthetic credentials only."""
import io
import json
import os
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from app.chatgpt_auth import AuthError, ChatGPTAuth, ISSUER, RESOURCE, SCOPES
from app.provider import ChatGPTProvider, ProviderError, ResponsesProvider, read_sse


class FakeOpenAI:
    def __init__(self):
        self.calls=[]
        self.scope=SCOPES
        self.fail_refresh=None
        self.revocation_error=False

    def __call__(self,url,data=None,token=None):
        self.calls.append((url,data,token))
        if url.endswith('openid-configuration'):
            return {'issuer':ISSUER,'authorization_endpoint':ISSUER+'/api/accounts/authorize',
                    'token_endpoint':ISSUER+'/api/accounts/oauth/token',
                    'jwks_uri':ISSUER+'/.well-known/jwks.json',
                    'revocation_endpoint':ISSUER+'/api/accounts/oauth/revoke'}
        if url.endswith('/token'):
            if data['grant_type']=='refresh_token' and self.fail_refresh:
                raise AuthError(self.fail_refresh)
            return {'id_token':'synthetic-id-token','access_token':'synthetic-access',
                    'refresh_token':'rotated-refresh' if data['grant_type']=='refresh_token' else 'synthetic-refresh',
                    'token_type':'Bearer','expires_in':120,'scope':self.scope}
        if url.endswith('/models'):
            return {'models':[{'slug':'test-model','display_name':'Test model','visibility':'list'},
                              {'slug':'hidden','visibility':'hidden'}]}
        if url.endswith('/revoke'):
            if self.revocation_error: raise AuthError('HTTP 503')
            return {}
        raise AssertionError('Unexpected URL')


class OAuthTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.net=FakeOpenAI()
        self.current_time=1000
        self.verify=lambda encoded,client,nonce: {'sub':'employee-test','email':'test@example.invalid'}
        self.auth=ChatGPTAuth(self.tmp.name,request=self.net,verify=self.verify,clock=lambda:self.current_time)

    def pending(self,account=None):
        state=self.auth.begin('http://127.0.0.1:8765','browser-binding',account)
        query=parse_qs(urlsplit(self.auth.authorize_url(state,'browser-binding')).query)
        return state,query

    def connect(self):
        state,query=self.pending()
        result=self.auth.complete({'state':state,'code':'synthetic-code','client_id':'oaiapp_synthetic'},'browser-binding')
        return result

    def test_pkce_scope_callback_and_protected_storage(self):
        state,query=self.pending()
        self.assertEqual(query['client_id'],['dynamic_agent_client'])
        self.assertEqual(query['redirect_uri'],['http://127.0.0.1:8765/auth/chatgpt/callback'])
        self.assertEqual(query['code_challenge_method'],['S256'])
        self.assertIn('chatgpt.tokens.use.direct',query['scope'][0])
        self.auth.complete({'state':state,'code':'synthetic-code','client_id':'oaiapp_synthetic'},'browser-binding')
        token_request=[c for c in self.net.calls if c[0].endswith('/token')][0][1]
        self.assertEqual(token_request['client_id'],'oaiapp_synthetic')
        self.assertEqual(token_request['resource'],RESOURCE)
        self.assertNotIn('synthetic-access',json.dumps(self.auth.status()))
        self.assertEqual(os.stat(self.auth.path).st_mode & 0o777,0o600)
        self.assertEqual(os.stat(self.tmp.name).st_mode & 0o777,0o700)

    def test_wrong_binding_expired_and_replayed_callbacks_rejected(self):
        state,_=self.pending()
        query={'state':state,'code':'code','client_id':'oaiapp_synthetic'}
        with self.assertRaises(AuthError): self.auth.complete(query,'other-browser')
        self.auth.complete(query,'browser-binding')
        with self.assertRaises(AuthError): self.auth.complete(query,'browser-binding')
        state,_=self.pending()
        self.current_time+=601
        with self.assertRaises(AuthError): self.auth.complete({'state':state},'browser-binding')

    def test_denial_does_not_exchange_code(self):
        state,_=self.pending()
        with self.assertRaises(AuthError): self.auth.complete({'state':state,'error':'access_denied'},'browser-binding')
        self.assertFalse(any(url.endswith('/token') for url,_,_ in self.net.calls))

    def test_returning_client_and_verified_identity_are_pinned(self):
        self.connect()
        key=self.auth.data['active']
        state,query=self.pending(key)
        self.assertEqual(query['client_id'],['oaiapp_synthetic'])
        self.assertNotIn('agent_name_hint',query)
        with self.assertRaises(AuthError):
            self.auth.complete({'state':state,'code':'code','client_id':'oaiapp_other'},'browser-binding')
        state,_=self.pending(key)
        self.auth.verify_override=lambda *args: {'sub':'other-person'}
        with self.assertRaises(AuthError):
            self.auth.complete({'state':state,'code':'code'},'browser-binding')
        self.assertEqual(self.auth.active()['subject'],'employee-test')

    def test_token_scope_not_callback_scope_controls_inference(self):
        self.net.scope='openid profile email'
        self.connect()
        self.assertTrue(self.auth.status()['connected'])
        self.assertFalse(self.auth.status()['plan_enabled'])
        with self.assertRaises(AuthError): self.auth.credentials()

    def test_refresh_rotation_and_scope_omission(self):
        self.connect()
        self.current_time+=70
        result=self.auth.credentials()
        self.assertEqual(result['refresh_token'],'rotated-refresh')
        request=[c[1] for c in self.net.calls if c[0].endswith('/token')][-1]
        self.assertEqual(request['grant_type'],'refresh_token')
        self.assertNotIn('scope',request)
        self.assertEqual(request['client_id'],'oaiapp_synthetic')

    def test_transient_refresh_preserves_credentials_terminal_clears(self):
        self.connect()
        self.current_time+=70
        self.net.fail_refresh='HTTP 503'
        with self.assertRaises(AuthError): self.auth.credentials()
        self.assertIn('refresh_token',self.auth.active())
        self.net.fail_refresh='HTTP 400 / invalid_grant'
        with self.assertRaises(AuthError): self.auth.credentials()
        self.assertNotIn('refresh_token',self.auth.active())
        self.assertEqual(self.auth.active()['client_id'],'oaiapp_synthetic')

    def test_model_catalog_and_selection_validate_account(self):
        self.connect()
        self.assertEqual(self.auth.models(),[{'id':'test-model','name':'Test model'}])
        key=self.auth.data['active']
        self.auth.select(key,'test-model')
        with self.assertRaises(AuthError): self.auth.select(key,'hidden')

    def test_signout_clears_tokens_and_retains_registration(self):
        self.connect()
        self.net.revocation_error=True
        result=self.auth.disconnect()
        self.assertFalse(result['remote_revocation_confirmed'])
        self.assertFalse(self.auth.status()['connected'])
        self.assertNotIn('id_token',self.auth.active())
        self.assertEqual(self.auth.active()['client_id'],'oaiapp_synthetic')

    def test_id_signature_issuer_audience_nonce_and_expiration(self):
        try:
            import jwt
            from cryptography.hazmat.primitives.asymmetric import rsa
        except ImportError:
            self.skipTest('Optional JWT/crypto dependencies not installed')
        key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        other=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        claims={'iss':ISSUER,'aud':'oaiapp_test','sub':'subject','nonce':'nonce',
                'iat':int(time.time()),'exp':int(time.time())+120}
        self.auth.verify_override=None
        class SigningKey:
            pass
        signing=SigningKey()
        signing.key=key.public_key()
        with patch('jwt.PyJWKClient') as jwks:
            jwks.return_value.get_signing_key_from_jwt.return_value=signing
            good=jwt.encode(claims,key,algorithm='RS256')
            self.assertEqual(self.auth.validate_identity(good,'oaiapp_test','nonce')['sub'],'subject')
            for token,client,nonce in [(good,'wrong-audience','nonce'),(good,'oaiapp_test','wrong-nonce'),
                    (jwt.encode(dict(claims,iss='https://attacker.invalid'),key,algorithm='RS256'),'oaiapp_test','nonce'),
                    (jwt.encode(dict(claims,exp=int(time.time())-20),key,algorithm='RS256'),'oaiapp_test','nonce'),
                    (jwt.encode(claims,other,algorithm='RS256'),'oaiapp_test','nonce')]:
                with self.assertRaises(AuthError): self.auth.validate_identity(token,client,nonce)


class StreamTests(unittest.TestCase):
    def stream(self,*events):
        return io.BytesIO(''.join('data: '+json.dumps(e)+'\n\n' for e in events).encode())

    def test_completed_output_only(self):
        result=read_sse(self.stream({'type':'response.output_item.added','item':{'type':'function_call'}},
                                   {'type':'response.completed','response':{'status':'completed','output':[{'type':'function_call'}]}}))
        self.assertEqual(len(result['output']),1)

    def test_completed_empty_output_uses_finalized_streamed_items(self):
        call={'id':'fc_test','type':'function_call','name':'get_profile','namespace':'it_support',
              'call_id':'call_test','arguments':'{}','status':'completed'}
        result=read_sse(self.stream({'type':'response.output_item.done','output_index':0,'item':call},
                                   {'type':'response.completed','response':{'status':'completed','output':[]}}))
        self.assertEqual(result['output'],[call])

    def test_incomplete_and_quota_error_never_look_successful(self):
        for event in [{'type':'response.incomplete'},
                      {'type':'response.failed','response':{'error':{'code':'subscription_sharing_usage_limit_exceeded'}}}]:
            with self.assertRaises(ProviderError): read_sse(self.stream(event))
        with self.assertRaises(ProviderError): read_sse(self.stream({'type':'response.created'}))

    def test_transport_timeout_retries_once_and_requires_completion(self):
        class Auth:
            def credentials(self,key): return {'access_token':'synthetic','models':[{'id':'model'}]}
        calls=[]
        def opener(request,timeout):
            calls.append(request)
            if len(calls)==1: raise TimeoutError('synthetic timeout')
            return self.stream({'type':'response.completed','response':{'status':'completed','output':[]}})
        result=ChatGPTProvider(Auth(),'account','model',opener,sleep=lambda _:None).request([])
        self.assertEqual(len(calls),2)
        self.assertEqual(result['_transport_retries'],1)
        self.assertEqual(result['_transport_retry_errors'],['TimeoutError'])

    def test_repeated_transport_failure_is_bounded(self):
        class Auth:
            def credentials(self,key): return {'access_token':'synthetic','models':[{'id':'model'}]}
        calls=[]
        def opener(request,timeout):
            calls.append(request)
            raise ConnectionResetError('synthetic reset')
        with self.assertRaises(ProviderError) as error:
            ChatGPTProvider(Auth(),'account','model',opener,sleep=lambda _:None).request([])
        self.assertEqual(len(calls),2)
        self.assertEqual(error.exception.transport_retries,1)

    def test_quota_error_does_not_retry(self):
        import urllib.error
        class Auth:
            def credentials(self,key): return {'access_token':'synthetic','models':[{'id':'model'}]}
        calls=[]
        def opener(request,timeout):
            calls.append(request)
            body=io.BytesIO(json.dumps({'error':{'code':'subscription_sharing_usage_limit_exceeded'}}).encode())
            raise urllib.error.HTTPError('https://api.openai.com/v1/responses',429,'quota',{},body)
        with self.assertRaises(ProviderError):
            ChatGPTProvider(Auth(),'account','model',opener,sleep=lambda _:None).request([])
        self.assertEqual(len(calls),1)

    def test_chatgpt_contract_separate_from_api_key(self):
        class Auth:
            def credentials(self,key):
                return {'access_token':'synthetic-oauth','models':[{'id':'account-model'}]}
        requests=[]
        def opener(request,timeout):
            requests.append(request)
            return self.stream({'type':'response.completed','response':{'status':'completed','output':[]}})
        with patch.dict(os.environ,{'OPENAI_API_KEY':'synthetic-api-key','OPENAI_MODEL':'api-model'}):
            ChatGPTProvider(Auth(),'account','account-model',opener).request([{'role':'user','content':'VPN'}])
            req=requests[0]
            payload=json.loads(req.data)
            self.assertTrue(payload['stream'])
            self.assertFalse(payload['store'])
            self.assertNotIn('max_output_tokens',payload)
            self.assertEqual(payload['tools'][0]['type'],'namespace')
            self.assertEqual(req.get_header('Authorization'),'Bearer synthetic-oauth')
            sent=[]
            api=ResponsesProvider(lambda p: sent.append(p) or {'output':[]})
            api.request([])
            self.assertEqual(sent[0]['model'],'api-model')
            self.assertIn('max_output_tokens',sent[0])
            self.assertEqual(api.key,'synthetic-api-key')


if __name__=='__main__': unittest.main()
