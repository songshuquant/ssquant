"""Auth rejection, node matching and recovery tests. All sockets are localhost."""
import copy
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import Mock, patch

from websockets.sync.server import serve
from ssquant.data import auth_manager as auth
from ssquant.data import ws_kline_client as ws_module
from ssquant.backtest.live_trading_adapter import LiveTradingAdapter, LiveDataSource

Client = ws_module.WSKlineClient


class AuthTests(unittest.TestCase):
    def setUp(self):
        auth.reset_auth()
        auth._last_auth_success_index = None
        auth.set_active_endpoint_index(0)
        auth.set_effective_data_server({
            'api_url': 'http://127.0.0.1:10001',
            'fallback_servers': [{'api_url': 'http://127.0.0.1:10002'}],
        })

    def tearDown(self):
        auth.reset_auth()
        auth.set_active_endpoint_index(None)
        auth._last_auth_success_index = None
        auth.set_effective_data_server(None)

    def test_explicit_node_ignores_cache_and_old_active_node(self):
        reply = Mock(status_code=200)
        reply.json.return_value = {'authenticated': True}
        with patch.object(auth.requests, 'get', return_value=reply) as get:
            self.assertTrue(auth.verify_auth('local-test', 'local-test'))
            self.assertTrue(auth.verify_auth('local-test', 'local-test'))
            self.assertEqual(get.call_count, 1)
            self.assertTrue(auth.verify_auth('local-test', 'local-test', endpoint_index=1))
            self.assertEqual(get.call_count, 2)
            self.assertEqual(get.call_args.args[0], 'http://127.0.0.1:10002/api/auth/verify')

    def test_explicit_node_does_not_accept_other_nodes_auth(self):
        with patch.object(auth.requests, 'get', side_effect=auth.requests.ConnectionError) as get:
            self.assertFalse(auth.verify_auth('local-test', 'local-test', endpoint_index=1))
            self.assertEqual(get.call_count, 1)
            self.assertEqual(get.call_args.args[0], 'http://127.0.0.1:10002/api/auth/verify')

    def test_rejection_replaces_prior_success(self):
        auth._auth_result = True
        reply = Mock(status_code=403)
        reply.json.return_value = {'authenticated': False, 'message': 'rejected'}
        with patch.object(auth.requests, 'get', return_value=reply):
            self.assertFalse(auth.verify_auth('local-test', 'local-test', endpoint_index=0))
            self.assertFalse(auth.is_authenticated())

    def test_missing_http_node_fails_without_request(self):
        with patch.object(auth.requests, 'get') as get:
            self.assertFalse(auth.verify_auth('local-test', 'local-test', endpoint_index=2))
            get.assert_not_called()

    def test_adapter_returns_verification_result_and_target(self):
        adapter = LiveTradingAdapter.__new__(LiveTradingAdapter)
        adapter.ws_kline_client = SimpleNamespace(endpoint_index=1)
        for result in (False, True):
            with self.subTest(result=result), patch.object(auth, 'verify_auth', return_value=result) as verify:
                self.assertIs(adapter._reauth_for_ws(), result)
                verify.assert_called_once_with(endpoint_index=1)


class CallbackTests(unittest.TestCase):
    def test_error_close_frame_recovers_auth_even_when_on_close_loses_code(self):
        client = Client()
        client._on_ws_error(None, SimpleNamespace(opcode=8, data=b'\x0f\xa1Unauthorized'))
        client._on_close(None, None, None)
        self.assertTrue(client._need_reauth)

    def test_new_library_exception_recovers_auth(self):
        client = Client()
        client._on_ws_error(None, SimpleNamespace(status_code=4001))
        self.assertTrue(client._need_reauth)

    def test_structured_close_recovers_auth(self):
        client = Client()
        client._on_close(None, 4001, 'Unauthorized')
        self.assertTrue(client._need_reauth)

    def test_other_close_and_text_errors_do_not_trigger_auth(self):
        for error in (SimpleNamespace(opcode=8, data=b'\x03\xe8done'),
                      SimpleNamespace(opcode=8, data=b''),
                      RuntimeError('4001 in application text')):
            with self.subTest(error=error):
                client = Client()
                client._on_ws_error(None, error)
                self.assertFalse(client._need_reauth)

    def test_open_is_not_ready_and_duplicate_welcome_does_not_resubscribe(self):
        client = Client()
        client._ws = Mock()
        client.on_connected = Mock()
        client.subscribe_kline('AU2612', '1m', preload=10)
        client._on_open(None)
        self.assertFalse(client.connected)
        self.assertFalse(client._connect_event.is_set())
        client._ws.send.assert_not_called()
        client._handle_message('{"type":"welcome"}')
        client._handle_message('{"type":"welcome"}')
        self.assertTrue(client.connected)
        self.assertTrue(client._connect_event.is_set())
        self.assertEqual(client._ws.send.call_count, 1)
        client.on_connected.assert_called_once()

    def test_auth_false_none_or_exception_never_attempts_ws(self):
        for result in (False, None, RuntimeError('local verification failed')):
            with self.subTest(result=result):
                client = Client(reconnect_interval=0.1, max_reconnect_attempts=2)
                client._running = client._need_reauth = True
                client.on_auth_required = Mock(**({'side_effect': result} if isinstance(result, Exception)
                                                else {'return_value': result}))
                client._do_connect = Mock()
                client._run_loop()
                client._do_connect.assert_not_called()
                self.assertTrue(client._need_reauth)
                self.assertFalse(client._running)
                self.assertEqual(client.on_auth_required.call_count, 3)

    def test_auth_failure_without_callback_stops(self):
        client = Client(reconnect_interval=0.1)
        client._running = client._need_reauth = True
        client._do_connect = Mock()
        client._run_loop()
        client._do_connect.assert_not_called()
        self.assertFalse(client._running)

    def test_network_rotation_revalidates_new_target_before_connecting(self):
        client = Client(ws_urls=['ws://localhost:1', 'ws://localhost:2'], reconnect_interval=0.1)
        events = []
        def connect():
            events.append(('connect', client.endpoint_index))
            if client.endpoint_index == 0:
                raise ConnectionRefusedError()
            client._running = False
        client._running = True
        client.on_auth_required = lambda: events.append(('auth', client.endpoint_index)) or True
        client._do_connect = connect
        client._run_loop()
        self.assertEqual(events, [('connect', 0), ('auth', 1), ('connect', 1)])

    def test_auth_rejection_revalidates_same_node_before_rotating(self):
        client = Client(ws_urls=['ws://localhost:1', 'ws://localhost:2'], reconnect_interval=0.1)
        events = []
        def connect():
            events.append(('connect', client.endpoint_index))
            if len(events) == 1:
                client._on_close(None, 4001, 'Unauthorized')
            else:
                client._running = False
        client._running = True
        client.on_auth_required = lambda: events.append(('auth', client.endpoint_index)) or True
        client._do_connect = connect
        client._run_loop()
        self.assertEqual(events, [('connect', 0), ('auth', 0), ('connect', 0)])

    def test_disabled_reconnect_does_not_auth_or_retry(self):
        client = Client(auto_reconnect=False)
        client._running = True
        client._do_connect = Mock(side_effect=lambda: client._on_close(None, 4001, 'Unauthorized'))
        client.on_auth_required = Mock()
        client._run_loop()
        self.assertEqual(client._do_connect.call_count, 1)
        client.on_auth_required.assert_not_called()

    def test_repeated_open_then_4001_does_not_reset_retry_limit(self):
        client = Client(reconnect_interval=0.1, max_reconnect_attempts=2)
        client._running = True
        client.on_connected = Mock()
        client.on_auth_required = Mock(return_value=True)
        def reject():
            client._on_open(None)
            client._on_close(None, 4001, 'Unauthorized')
        client._do_connect = Mock(side_effect=reject)
        client._run_loop()
        self.assertEqual(client._do_connect.call_count, 3)
        self.assertEqual(client.on_auth_required.call_count, 2)
        client.on_connected.assert_not_called()
        self.assertFalse(client.connected)

    def test_failed_auth_can_recover_on_other_node_without_unauthenticated_socket(self):
        client = Client(ws_urls=['ws://localhost:1', 'ws://localhost:2'], reconnect_interval=0.1)
        client._running = client._need_reauth = True
        events = []
        def verify():
            events.append(('auth', client.endpoint_index))
            return client.endpoint_index == 1
        def connect():
            events.append(('connect', client.endpoint_index))
            client._running = False
        client.on_auth_required = verify
        client._do_connect = connect
        client._run_loop()
        self.assertEqual(events, [('auth', 0), ('auth', 1), ('connect', 1)])


class LoopbackTests(unittest.TestCase):
    @staticmethod
    def bar(minute):
        return {'datetime': f'2026-10-21 09:{minute:02d}:00', 'open': 100, 'high': 102,
                'low': 99, 'close': 101, 'volume': 0 if minute == 1 else 12,
                'turnover': None, 'openint': -2, 'cumulative_openint': 1000 - minute * 2,
                'buy_volume': None, 'sell_volume': 0, 'is_complete': True}

    def exercise(self, reject_initial=False):
        calls, subscriptions, histories, klines, ready = [], [], [], [], []
        auth_ok = threading.Event()
        done = threading.Event()
        errors = []
        client = None
        source = LiveDataSource('au2612', {'kline_source': 'data_server', 'lookback_bars': 100})
        bars = [self.bar(i) for i in range(6)]

        class VerifyHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                calls.append('http_verify')
                auth_ok.set()
                payload = b'{"authenticated": true}'
                self.send_response(200)
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            def log_message(self, *args):
                pass

        def handler(ws):
            try:
                calls.append('ws_open')
                attempt = calls.count('ws_open')
                if (reject_initial and attempt == 1) or (attempt > 1 and not auth_ok.is_set()):
                    ws.close(4001, 'Unauthorized: Bearer token required; legacy clients must call /api/auth/verify first')
                    return
                ws.send(json.dumps({'type': 'welcome'}))
                sub = json.loads(ws.recv(timeout=4))
                subscriptions.append(sub)
                ws.send(json.dumps({'type': 'subscribed', **sub}))
                history = bars[:2] if not reject_initial and attempt == 1 else bars[:5]
                ws.send(json.dumps({'type': 'history', 'symbol': 'au2612', 'period': '1M',
                                    'data': history, 'count': len(history)}))
                bar = bars[2] if not reject_initial and attempt == 1 else bars[5]
                ws.send(json.dumps({'type': 'kline', 'symbol': 'au2612', 'period': '1M', 'data': bar}))
                if not reject_initial and attempt == 1:
                    ws.close(4001, 'Unauthorized: Bearer token required; legacy clients must call /api/auth/verify first')
                else:
                    done.wait(4)
                    # Wait for the client's orderly close, not a timed artificial disconnection.
                    try:
                        ws.recv(timeout=4)
                    except Exception:
                        pass
            except Exception as error:
                errors.append(repr(error))

        with ThreadingHTTPServer(('127.0.0.1', 0), VerifyHandler) as http, \
                serve(handler, '127.0.0.1', 0, close_timeout=0.2) as ws_server:
            http_thread = threading.Thread(target=http.serve_forever, daemon=True)
            ws_thread = threading.Thread(target=ws_server.serve_forever, daemon=True)
            http_thread.start()
            ws_thread.start()
            auth.set_effective_data_server({'api_url': f'http://127.0.0.1:{http.server_port}'})
            client = Client(ws_url=f'ws://127.0.0.1:{ws_server.socket.getsockname()[1]}',
                            reconnect_interval=0.1, max_reconnect_attempts=3)
            def history_callback(symbol, period, data):
                histories.append(copy.deepcopy(data))
                source.on_ws_history(data)
            def kline_callback(symbol, period, data):
                klines.append(copy.deepcopy(data))
                source.on_ws_kline(data)
                if klines[-1] == bars[5]:
                    done.set()
            client.on_history = history_callback
            client.on_kline = kline_callback
            client.on_connected = lambda: ready.append(calls.count('ws_open'))
            client.on_auth_required = lambda: auth.verify_auth('local-test', 'local-test',
                                                              endpoint_index=client.endpoint_index)
            client.subscribe_kline('au2612', '1M', preload=100)
            try:
                self.assertTrue(client.connect(timeout=5))
                self.assertTrue(done.wait(5), f'delivery missing: {calls}, errors={errors}')
                self.assertEqual(calls, ['ws_open', 'http_verify', 'ws_open'])
                self.assertEqual(ready, [2] if reject_initial else [1, 2])
                self.assertEqual(len(subscriptions), 1 if reject_initial else 2)
                self.assertTrue(all(s == {'action': 'subscribe_kline', 'symbol': 'au2612',
                                         'period': '1M', 'preload': 100} for s in subscriptions))
                self.assertEqual(histories[-1], bars[:5])
                self.assertEqual(klines[-1], bars[5])
                self.assertEqual([str(b['datetime']) for b in source.klines], [b['datetime'] for b in bars])
                # The framework's existing history merge must preserve the actual data fields.
                for actual, expected in zip(source.klines, bars):
                    for field, value in expected.items():
                        if field != 'datetime':
                            self.assertEqual(actual[field], value, field)
                self.assertFalse(errors)
            finally:
                done.set()
                client.close()
                http.shutdown()
                ws_server.shutdown()
                http_thread.join(2)
                ws_thread.join(2)
                auth.reset_auth()
                auth.set_effective_data_server(None)
                auth.set_active_endpoint_index(None)
                auth._last_auth_success_index = None
            self.assertFalse(client._thread.is_alive(), 'client thread leaked')
            self.assertFalse(client.connected)

    def test_initial_4001_then_real_http_verify_and_subscription(self):
        self.exercise(reject_initial=True)

    def test_auth_loss_after_data_recovers_history_gap_and_realtime(self):
        self.exercise(reject_initial=False)


if __name__ == '__main__':
    unittest.main()
