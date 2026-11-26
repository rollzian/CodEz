import unittest
from studio_bridge.protocol import BridgeError,RPCError,decode
from studio_bridge.transport import Client

class HardeningTests(unittest.TestCase):
    def test_nonfinite_exponent_rejected(self):
        for data in (b'{"x":1e999}',b'{"x":-1e999}'):
            with self.assertRaises(RPCError):decode(data)
    def test_response_boolean_id_and_dual_result_rejected(self):
        class Transport:
            def __init__(self,mode):self.mode=mode;self.closed=False
            def exchange(self,msg):
                value={'jsonrpc':'2.0','id':True if self.mode=='bool' else msg['id'],'result':{'protocolVersion':'2025-11-25'}}
                if self.mode=='dual':value['error']={'code':-1,'message':'error'}
                return value
            def close(self):self.closed=True
        for mode in ('bool','dual'):
            t=Transport(mode)
            with self.assertRaises(BridgeError):Client(t)
            self.assertTrue(t.closed)
