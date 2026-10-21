"""Framework K-line callbacks over ssquantdata's authenticated realtime stream.

The SDK rotates Bearers and verifies exact sequence replay. Unrecoverable gaps
remain terminal; unverified history snapshots never establish continuity.
"""
import threading
from typing import Dict, Optional

try:
    from ssquantdata import KlineChannel, GapEvent, RecoveryEvent, RealtimeGapError, SSQuantDataError
    WEBSOCKET_AVAILABLE = True
except ImportError:
    WEBSOCKET_AVAILABLE = False

from .sdk_client import get_sdk_client


class WSKlineClient:
    def __init__(self, *, client=None):
        self._client = client
        self._stream = None
        self._thread = None
        self._connected = False
        self._running = False
        self._ready = threading.Event()
        self._sub_lock = threading.RLock()
        self._callback_lock = threading.RLock()
        self._active_subscriptions = {}
        self.error = None
        self.on_kline = None
        self.on_history = None
        self.on_connected = None
        self.on_disconnected = None
        self.on_error = None
        self.on_gap = None
        self.on_recovering = None
        self.on_recovered = None
        self.stats = {'klines_received': 0, 'history_received': 0}

    @property
    def connected(self):
        return (self._connected and not bool(getattr(self._stream, 'recovering', False))
                and bool(getattr(self._stream, 'connected', True)))

    def connect(self, timeout=10.0):
        if not WEBSOCKET_AVAILABLE:
            raise ImportError('远程数据需要 ssquantdata，请安装项目依赖')
        if self._running:
            return self.connected
        if self.error is not None:
            raise self.error
        self._client = self._client or get_sdk_client()
        self._stream = self._client.realtime()
        self._running = True
        self._ready.clear()
        self._thread = threading.Thread(target=self._consume, args=(timeout,), daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout):
            self.close()
            return False
        return self.connected

    def subscribe_kline(self, symbol, period, preload=100):
        # SDK validation and normalization are shared by history and realtime.
        channel = KlineChannel(symbol, period, preload)
        payload = channel.payload()
        if not isinstance(preload, int) or preload < 0:
            raise ValueError('preload 必须是大于等于 0 的整数')
        key = (payload['symbol'], payload['period'])
        with self._sub_lock:
            self._active_subscriptions[key] = {
                'symbol': key[0], 'period': key[1], 'preload': preload,
            }
            if self.connected:
                # Existing channels need no additional snapshot when adding one channel.
                self._replace_channels(new_key=key)

    def _replace_channels(self, new_key=None):
        with self._sub_lock:
            channels = []
            for key, sub in self._active_subscriptions.items():
                count = sub['preload'] if new_key is None or key == new_key else 0
                # The public WS protocol caps a snapshot at 1000. Larger framework
                # lookbacks use the SDK HTTP API, without silently truncating them.
                if count > 1000:
                    self._history(sub, count)
                    count = 0
                channels.append(KlineChannel(sub['symbol'], sub['period'], count))
            self._stream.replace_subscriptions(channels)

    def refresh_history(self, symbol, period, preload: Optional[int] = None):
        payload = KlineChannel(symbol, period).payload()
        key = (payload['symbol'], payload['period'])
        with self._sub_lock:
            sub = self._active_subscriptions.get(key)
        if sub is None or not self.connected:
            return False
        count = sub['preload'] if preload is None else preload
        if not isinstance(count, int) or count < 0:
            raise ValueError('preload 必须是大于等于 0 的整数或 None')
        if count:
            self._history(sub, count)
        return True

    def _history(self, sub, count):
        result = self._client.futures.history(
            sub['symbol'], sub['period'], limit=count, preload=True, cache=False,
        )
        if result.status != 'ok':
            raise SSQuantDataError(result.message)
        self._handle_message({'type': 'history', 'symbol': sub['symbol'],
                              'period': sub['period'], 'data': result.records})

    def _consume(self, timeout):
        try:
            self._stream.connect(timeout=timeout)
            for event in self._stream:
                if not self._running:
                    break
                if isinstance(event, GapEvent):
                    self._connected = False
                    if self.on_gap:
                        self.on_gap(event)
                    # The SDK next raises RealtimeGapError after delivering the gap.
                    continue
                if isinstance(event, RecoveryEvent):
                    self._connected = not self._stream.recovering
                    if self.connected and self.on_recovered:
                        self.on_recovered()
                    continue
                self._handle_message(event)
        except Exception as exc:
            self.error = exc
            if self._running and self.on_error:
                self.on_error(exc)
        finally:
            self._connected = self._running = False
            self._ready.set()
            self._stream.close()
            if self.on_disconnected:
                self.on_disconnected()

    def _handle_message(self, message):
        kind = message.get('type')
        if kind == 'recovering':
            self._connected = False
            if self.on_recovering:
                self.on_recovering()
        elif kind == 'welcome':
            if not self._connected:
                self._replace_channels()
                self._connected = True
                self._ready.set()
                if self.on_connected:
                    self.on_connected()
        elif kind in {'kline', 'history'}:
            key = (str(message.get('symbol', '')).lower(),
                   str(message.get('period', '')).upper())
            with self._sub_lock:
                subscribed = key in self._active_subscriptions
            if not subscribed:
                return
            data = message.get('data', {} if kind == 'kline' else [])
            with self._callback_lock:
                if kind == 'history':
                    self.stats['history_received'] += len(data)
                    if self.on_history:
                        self.on_history(*key, data)
                elif data:
                    self.stats['klines_received'] += 1
                    if self.on_kline:
                        self.on_kline(*key, data)
        elif kind == 'error':
            raise SSQuantDataError(str(message.get('message', '实时数据请求失败')))

    def close(self):
        self._running = self._connected = False
        if self._stream is not None:
            self._stream.close()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=3.0)

    def get_stats(self) -> Dict:
        return {**self.stats, 'connected': self.connected,
                'active_subscriptions': len(self._active_subscriptions)}
