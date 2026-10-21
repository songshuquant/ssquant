"""Official SDK integration: loopback network only, no account or CTP actions."""
import copy
import json
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from queue import Queue, Empty
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import urlsplit, parse_qs

import pandas as pd
import pytest
from websockets.sync.server import serve
from ssquantdata import AuthenticationError, ClientConfig, GapEvent, RealtimeGapError, SSQuantDataClient

from ssquant.data import sdk_client, auth_manager
from ssquant.data.api_data_fetcher import fetch_data_from_api, get_futures_data
from ssquant.data.historical_preloader import HistoricalDataPreloader
from ssquant.data.ws_kline_client import WSKlineClient
from ssquant.backtest.live_trading_adapter import LiveTradingAdapter, LiveDataSource


def bar(minute=0):
    return {'datetime': f'2026-10-21 09:{minute:02d}:00', 'symbol': 'rb777',
            'real_symbol': 'rb2701', 'open': 3000, 'high': 3002, 'low': 2998,
            'close': 3001, 'volume': 0 if minute == 0 else 20, 'amount': None,
            'openint': -5, 'cumulative_openint': 1000, 'B': None, 'S': 0,
            'buy_volume': None, 'sell_volume': 0, 'orderflow_known_bars': 2,
            'orderflow_total_bars': 3, 'is_complete': True}


class LocalServices:
    def __init__(self):
        self.http_calls = []
        self.ws_connections = []
        self.subscriptions = Queue()
        self.messages = Queue()
        self.rows = [bar(0), bar(1)]
        self.reject_history_once = False
        self.reject_login = False
        self.auto_welcome = True
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, status, payload):
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                outer.http_calls.append((self.path, {}, self.headers.get('Authorization')))
                if self.path == '/v1/auth/login/password':
                    if outer.reject_login:
                        return self.reply(401, {'message': 'test login denied'})
                    assert payload['username'] == 'test-user'
                    assert payload['password'] == 'test-password'
                    return self.reply(200, {'access_token': 'test-token-1', 'refresh_token': 'test-refresh',
                                           'expires_in': 900, 'user': {'id': 'test-user-id'}})
                assert self.path == '/v1/auth/refresh'
                assert payload['refresh_token'] == 'test-refresh'
                self.reply(200, {'access_token': 'test-token-2', 'refresh_token': 'test-refresh',
                                 'expires_in': 900, 'user': {'id': 'test-user-id'}})

            def do_GET(self):
                parsed = urlsplit(self.path)
                params = parse_qs(parsed.query)
                outer.http_calls.append((parsed.path, params, self.headers.get('Authorization')))
                if parsed.path == '/api/ssquant/capabilities':
                    return self.reply(200, {'api_version': '1.0', 'raw_only': True,
                                           'history': {'source_max_bars': 100000}})
                assert parsed.path == '/api/futures/history', parsed.path
                if outer.reject_history_once:
                    outer.reject_history_once = False
                    return self.reply(401, {'message': 'test token expired'})
                self.reply(200, {'code': 0, 'data': {'count': len(outer.rows), 'klines': outer.rows}})

        self.http = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.http_thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        def ws_handler(ws):
            outer.ws_connections.append(ws.request.headers.get('Authorization'))
            if outer.auto_welcome:
                ws.send(json.dumps({'type': 'welcome', 'stream_id': 'loopback-stream'}))
            # Receive subscription commands and send test-controlled server data.
            def send_messages():
                while True:
                    item = outer.messages.get()
                    if item is None:
                        return
                    try:
                        if isinstance(item, tuple):
                            ws.close(*item)
                            return
                        ws.send(json.dumps(item))
                    except Exception:
                        return
            sender = threading.Thread(target=send_messages, daemon=True)
            sender.start()
            try:
                for incoming in ws:
                    outer.subscriptions.put(json.loads(incoming))
            finally:
                outer.messages.put(None)
                sender.join(2)
        self.ws = serve(ws_handler, '127.0.0.1', 0, close_timeout=0.2)
        self.ws_thread = threading.Thread(target=self.ws.serve_forever, daemon=True)

    def __enter__(self):
        self.http_thread.start()
        self.ws_thread.start()
        return self

    def __exit__(self, *args):
        self.messages.put(None)
        self.http.shutdown()
        self.ws.shutdown()
        self.http_thread.join(2)
        self.ws_thread.join(2)

    def config(self):
        base = f'http://127.0.0.1:{self.http.server_port}'
        return ClientConfig(auth_url=base, http_base_url=base,
                            member_base_url=base, ws_url=f'ws://127.0.0.1:{self.ws.socket.getsockname()[1]}',
                            device_id='ssquant-integration-test', allow_insecure=True, cache_enabled=False,
                            connect_timeout=1, read_timeout=5)

    def live(self, seq, minute=2, period='1M'):
        self.messages.put({'type': 'kline', 'stream_id': 'loopback-stream',
                           'channel': f'kline:rb777:{period}', 'symbol': 'rb777',
                           'period': period, 'seq': seq, 'data': bar(minute)})


@pytest.fixture
def services():
    with LocalServices() as item:
        yield item


@pytest.fixture(autouse=True)
def clean_sessions():
    sdk_client.close_sdk_clients()
    sdk_client.configure_data_server(None)
    yield
    sdk_client.close_sdk_clients()
    sdk_client.configure_data_server(None)


def configured_client(services, monkeypatch):
    config = services.config()
    monkeypatch.setenv('SSQUANTDATA_USERNAME', 'test-user')
    monkeypatch.setenv('SSQUANTDATA_PASSWORD', 'test-password')
    monkeypatch.delenv('SSQUANTDATA_ACCESS_TOKEN', raising=False)
    monkeypatch.delenv('SSQUANTDATA_REFRESH_TOKEN', raising=False)
    monkeypatch.setattr(ClientConfig, 'from_env', classmethod(lambda cls: config))
    return sdk_client.get_sdk_client()


@pytest.mark.parametrize('period', ['1M', '5M', '15M', '30M', '1H', '1D', '7M', '2H', '1W', '1Y', '1MON'])
def test_history_and_preload_share_sdk_and_preserve_raw_fields(services, monkeypatch, period):
    client = configured_client(services, monkeypatch)
    assert auth_manager.verify_auth()
    assert sdk_client.get_sdk_client() is client
    frame = fetch_data_from_api('RB777', '2026-10-01', '2026-10-21', None, None, period, '0', 'no')
    preloaded = HistoricalDataPreloader()._fetch_from_data_server('rb777', period, 500, '0')
    pd.testing.assert_frame_equal(frame, preloaded)
    assert frame.index.name == 'datetime'
    assert frame.iloc[0]['volume'] == 0 and frame.iloc[0]['openint'] == -5
    assert pd.isna(frame.iloc[0]['amount']) and pd.isna(frame.iloc[0]['B'])
    assert frame.iloc[0]['S'] == 0 and frame.iloc[0]['orderflow_known_bars'] == 2
    assert frame.iloc[0]['real_symbol'] == 'rb2701'
    paths = [path for path, *_ in services.http_calls]
    assert paths.count('/v1/auth/login/password') == 1
    assert '/api/auth/verify' not in paths
    assert all(header.startswith('Bearer ') for path, _, header in services.http_calls
               if not path.startswith('/v1/auth/'))
    calls = [params for path, params, _ in services.http_calls if path == '/api/futures/history']
    assert all(call['period'] == [period] and call['adjust_type'] == ['0'] for call in calls)


def test_expired_http_token_is_refreshed_by_sdk(services, monkeypatch):
    configured_client(services, monkeypatch)
    assert auth_manager.verify_auth()
    services.reject_history_once = True
    frame = sdk_client.history_frame('rb777', '1M', limit=2)
    assert len(frame) == 2
    paths = [path for path, *_ in services.http_calls]
    assert paths.count('/v1/auth/refresh') == 1
    assert paths.count('/v1/auth/login/password') == 1
    histories = [header for path, _, header in services.http_calls if path == '/api/futures/history']
    assert histories == ['Bearer test-token-1', 'Bearer test-token-2']
    live = WSKlineClient()
    try:
        assert live.connect(timeout=2)
        assert services.ws_connections == ['Bearer test-token-2']
    finally:
        live.close()


def test_auth_denial_is_not_empty_history_success(services, monkeypatch):
    configured_client(services, monkeypatch)
    services.reject_login = True
    assert not auth_manager.verify_auth()
    assert 'test login denied' in auth_manager.get_auth_message()
    with pytest.raises(AuthenticationError):
        fetch_data_from_api('rb777', None, None, None, None, '1M', '0', 'no', limit=2)
    assert not any(path == '/api/futures/history' for path, *_ in services.http_calls)


def test_legitimate_empty_history_is_empty_frame(services, monkeypatch):
    configured_client(services, monkeypatch)
    services.rows = []
    frame = sdk_client.history_frame('rb777', '1M', limit=2)
    assert frame.empty and frame.index.name == 'datetime'


def test_exact_time_and_limit_request_modes(services, monkeypatch):
    configured_client(services, monkeypatch)
    fetch_data_from_api('rb777', None, None, None, None, '1M', '0', 'no',
                        start_time='2026-10-21 09:00:00', end_time='2026-10-21 09:01:00', limit=2)
    calls = [p for path, p, _ in services.http_calls if path == '/api/futures/history']
    assert calls[-1]['start_time'] == ['2026-10-21 09:00:00']
    assert 'start_date' not in calls[-1]
    assert calls[-1]['limit'] == ['2']


def test_explicit_account_does_not_inherit_environment_token(monkeypatch, tmp_path):
    monkeypatch.setenv('SSQUANTDATA_ACCESS_TOKEN', 'other-account-token')
    monkeypatch.setenv('SSQUANTDATA_REFRESH_TOKEN', 'other-account-refresh')
    fake = Mock()
    monkeypatch.setattr('ssquantdata.SSQuantDataClient', fake)
    a = sdk_client.get_sdk_client('a', 'a-password')
    assert sdk_client.get_sdk_client('a', 'a-password') is a
    assert fake.call_args.kwargs['access_token'] is None
    assert fake.call_args.kwargs['refresh_token'] is None
    sdk_client.get_sdk_client('b', 'b-password')
    assert fake.call_count == 2


def test_legacy_node_configuration_requires_explicit_migration():
    with pytest.raises(ValueError, match='sdk_config'):
        sdk_client.configure_data_server({'api_url': 'http://127.0.0.1:8086'})


@pytest.mark.parametrize('period', ['1M', '7M', '1W', '1Y'])
def test_realtime_bearer_batch_subscriptions_and_raw_delivery(services, monkeypatch, period):
    configured_client(services, monkeypatch)
    client = WSKlineClient()
    received = Queue()
    history = Queue()
    client.on_kline = lambda *args: received.put(args)
    client.on_history = lambda *args: history.put(args)
    client.subscribe_kline('RB777', period, 100)
    client.subscribe_kline('AU888', '1M', 50)
    try:
        assert client.connect(timeout=2)
        sub = services.subscriptions.get(timeout=2)
        assert sub == {'action': 'replace_subscriptions', 'channels': [
            {'type': 'kline', 'symbol': 'rb777', 'period': period, 'preload': 100},
            {'type': 'kline', 'symbol': 'au888', 'period': '1M', 'preload': 50}]}
        services.messages.put({'type': 'history', 'symbol': 'rb777', 'period': period,
                               'stream_id': 'loopback-stream', 'snapshot_seq': 900, 'data': [bar(0), bar(1)]})
        services.live(10, period=period)
        assert history.get(timeout=2) == ('rb777', period, [bar(0), bar(1)])
        assert received.get(timeout=2) == ('rb777', period, bar(2))
        assert services.ws_connections == ['Bearer test-token-1']
    finally:
        client.close()
    assert not client._thread.is_alive()


@pytest.mark.parametrize('failure', ['sequence_gap', 'auth_close'])
def test_terminal_gap_stops_adapter_without_reconnect(services, monkeypatch, failure):
    configured_client(services, monkeypatch)
    adapter = LiveTradingAdapter.__new__(LiveTradingAdapter)
    adapter.running = True
    adapter._ws_preload_done = threading.Event()
    adapter._runtime_state_lock = threading.Lock()
    adapter._runtime_state = {}
    client = WSKlineClient()
    delivered, gaps = Queue(), Queue()
    client.on_kline = lambda *args: delivered.put(args)
    client.on_error = adapter._on_ws_failure
    client.on_gap = gaps.put
    client.subscribe_kline('rb777', '1M', 0)
    try:
        assert client.connect(timeout=2)
        services.subscriptions.get(timeout=2)
        services.live(100)
        assert delivered.get(timeout=2)[2] == bar(2)
        if failure == 'sequence_gap':
            services.live(102, minute=4)
        else:
            services.messages.put((4001, 'Unauthorized'))
        assert isinstance(gaps.get(timeout=2), GapEvent)
        assert adapter._ws_preload_done.wait(2)
        assert not adapter.running
        assert isinstance(adapter._remote_data_error, RealtimeGapError)
        client._thread.join(2)
        assert not client.connected and not client._thread.is_alive()
        assert len(services.ws_connections) == 1
        assert delivered.empty()
    finally:
        client.close()


def test_large_lookback_uses_sdk_http_without_ws_truncation(services, monkeypatch):
    configured_client(services, monkeypatch)
    client = WSKlineClient()
    history = Queue()
    client.on_history = lambda *args: history.put(args)
    client.subscribe_kline('rb777', '1M', 2500)
    try:
        assert client.connect(timeout=2)
        sub = services.subscriptions.get(timeout=2)
        assert sub['channels'][0]['preload'] == 0
        assert len(history.get(timeout=2)[2]) == 2
        calls = [p for path, p, _ in services.http_calls if path == '/api/futures/history']
        assert calls[-1]['limit'] == ['2500']
    finally:
        client.close()


def test_no_welcome_never_reports_ready(services, monkeypatch):
    configured_client(services, monkeypatch)
    services.auto_welcome = False
    client = WSKlineClient()
    connected = Mock()
    client.on_connected = connected
    try:
        assert not client.connect(timeout=0.2)
        connected.assert_not_called()
        assert not client.connected
    finally:
        client.close()


def test_history_merge_still_fills_gap_preserving_newer_bar():
    source = LiveDataSource('rb2701', {'kline_source': 'data_server', 'lookback_bars': 100})
    source.on_ws_history([copy.deepcopy(bar(0)), copy.deepcopy(bar(2))])
    source.on_ws_kline(copy.deepcopy(bar(3)))
    source.on_ws_history([copy.deepcopy(bar(0)), copy.deepcopy(bar(1)), copy.deepcopy(bar(2))])
    assert [str(item['datetime']) for item in source.klines] == [bar(i)['datetime'] for i in range(4)]
    assert len(source.klines) == 4 and source.klines.maxlen == 100
    assert source.klines[0]['volume'] == 0 and source.klines[0]['B'] is None


def test_local_preload_does_not_construct_sdk(monkeypatch, tmp_path):
    db = tmp_path / 'backtest_data.db'
    with sqlite3.connect(db) as conn:
        pd.DataFrame([bar(0), bar(1)]).to_sql('rb777_1M_raw', conn, index=False)
    forbidden = Mock(side_effect=AssertionError('local data must not create a remote session'))
    monkeypatch.setattr(sdk_client, 'get_sdk_client', forbidden)
    preloader = HistoricalDataPreloader(str(db))
    result = preloader.preload('rb2701', '1M', history_symbol='rb777',
                               lookback_bars=2, kline_source='local', adjust_type='0')
    assert len(result) == 2 and result.iloc[0]['volume'] == 0
    forbidden.assert_not_called()


def test_local_tick_history_does_not_construct_sdk(monkeypatch, tmp_path):
    with sqlite3.connect(tmp_path / 'backtest_data.db') as conn:
        pd.DataFrame([{'datetime': '2026-10-21 09:00:00', 'LastPrice': 3000, 'Volume': 0}]).to_sql(
            'rb2701_tick', conn, index=False)
    forbidden = Mock(side_effect=AssertionError('local Tick must not use remote SDK'))
    monkeypatch.setattr(sdk_client, 'get_sdk_client', forbidden)
    result = get_futures_data('rb2701', kline_period='tick', cache_dir=str(tmp_path), limit=1)
    assert len(result) == 1 and result.iloc[0]['Volume'] == 0
    forbidden.assert_not_called()


def test_framework_adjustment_stays_local_and_runs_once(services, monkeypatch, tmp_path):
    from ssquant.data import local_adjust
    configured_client(services, monkeypatch)
    def adjust(frame, symbol, period, kind):
        result = frame.copy()
        result['close'] = result['close'] + 100
        return result
    adjusted = Mock(side_effect=adjust)
    monkeypatch.setattr(local_adjust, 'apply_local_adjust', adjusted)
    result = get_futures_data('rb777', kline_period='1M', adjust_type='2',
                              limit=2, use_cache=False, cache_dir=str(tmp_path))
    assert result.iloc[0]['close'] == 3101
    assert adjusted.call_count == 1 and adjusted.call_args.args[3] == '2'
    calls = [params for path, params, _ in services.http_calls if path == '/api/futures/history']
    assert calls[-1]['adjust_type'] == ['0']


def test_gap_stops_a_tick_callback_that_was_waiting_for_strategy_lock():
    waiting, release = threading.Event(), threading.Event()
    class Gate:
        def __enter__(self):
            waiting.set()
            assert release.wait(2)
        def __exit__(self, *args):
            pass
    adapter = LiveTradingAdapter.__new__(LiveTradingAdapter)
    adapter.running = True
    adapter.enable_tick_callback = True
    adapter._kline_source = 'local'
    adapter.multi_data_source = SimpleNamespace(data_sources=[
        SimpleNamespace(symbol='rb2701', update_tick=lambda data: None)])
    adapter.data_recorders = {}
    adapter._strategy_lock = Gate()
    adapter.strategy_func = Mock()
    adapter._runtime_state_lock = threading.Lock()
    adapter._runtime_state = {}
    adapter._ws_preload_done = threading.Event()
    thread = threading.Thread(target=adapter._process_tick_data, args=({'InstrumentID': 'rb2701'},))
    thread.start()
    try:
        assert waiting.wait(2)
        adapter._on_ws_failure(RealtimeGapError('test gap while waiting'))
    finally:
        release.set()
        thread.join(2)
    adapter.strategy_func.assert_not_called()
    assert not thread.is_alive()
