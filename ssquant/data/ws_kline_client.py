#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
WebSocket K线客户端
连接 data_server 实时数据服务器，接收预加载历史K线和实时K线推送

功能：
1. 连接 data_server WebSocket 服务器
2. 订阅 K线（支持 preload 参数预加载历史数据）
3. 接收实时 K线推送，通过回调通知上层
4. 自动断线重连
5. 线程安全，独立运行在后台线程

架构：
  服务端 ──(WebSocket)──→ 推送目标周期 K线（服务端聚合 1M → N 周期）
                              │
  客户端 WSKlineClient:       │
    subscribe_kline(au888, 5M, preload=100)
      └─ 向服务端订阅 5M (preload=100)
         → 获取历史 5M 数据 → on_history(5M)
         → 实时推送 5M K线  → on_kline(au888, 5M, kline)

  对策略层完全透明：live_trading_adapter.py 零改动。
"""

import json
import time
import threading
from typing import Dict, List, Optional, Callable, Set, Tuple
from datetime import datetime

# 尝试导入 websocket-client（注意：不是 websockets，这个更适合客户端）
try:
    import websocket
    WEBSOCKET_AVAILABLE = True
except ImportError:
    try:
        # 回退到 websockets（异步库，需要包装）
        import asyncio
        import websockets
        WEBSOCKET_AVAILABLE = True
        websocket = None  # 标记使用 websockets
    except ImportError:
        WEBSOCKET_AVAILABLE = False
        websocket = None


class WSKlineClient:
    """
    WebSocket K线客户端
    
    连接 data_server，接收实时K线推送和预加载历史数据。
    自动处理 1M → 高周期的本地聚合，对上层透明。
    
    使用方式:
        client = WSKlineClient(ws_url='ws://localhost:8087')
        client.on_kline = my_kline_handler       # 实时K线回调
        client.on_history = my_history_handler    # 历史K线回调
        client.on_connected = my_connect_handler  # 连接成功回调
        client.connect()
        
        # 订阅任意周期（包括 2M, 3M, 7M 等自定义周期）
        client.subscribe_kline('au888', '5M', preload=100)
    """
    
    def __init__(self, ws_url: str = 'ws://localhost:8087',
                 ws_urls: Optional[List[str]] = None,
                 auto_reconnect: bool = True,
                 reconnect_interval: float = 5.0,
                 max_reconnect_attempts: int = 0):
        """
        初始化 WebSocket K线客户端
        
        Args:
            ws_url: data_server WebSocket 地址（单地址时与 ws_urls 二选一）
            ws_urls: 多个 WebSocket 地址，主地址在前；断线重连时轮询下一地址
            auto_reconnect: 是否自动重连
            reconnect_interval: 重连间隔（秒）
            max_reconnect_attempts: 最大重连次数，0=无限
        """
        if ws_urls:
            self.ws_urls = list(ws_urls)
        else:
            self.ws_urls = [ws_url]
        self.ws_url = self.ws_urls[0]  # 兼容旧代码：当前主展示用
        self._url_index = 0
        self._ever_connected = False
        self.auto_reconnect = auto_reconnect
        self.reconnect_interval = reconnect_interval
        self.max_reconnect_attempts = max_reconnect_attempts
        
        # ========== 回调函数 ==========
        self.on_kline: Optional[Callable] = None          # on_kline(symbol, period, kline_dict)
        self.on_history: Optional[Callable] = None         # on_history(symbol, period, klines_list)
        self.on_connected: Optional[Callable] = None       # on_connected()
        self.on_disconnected: Optional[Callable] = None    # on_disconnected()
        self.on_error: Optional[Callable] = None           # on_error(error_msg)
        self.on_auth_required: Optional[Callable] = None   # 服务端要求重新鉴权时触发
        
        # ========== 连接状态 ==========
        self._ws = None              # websocket-client 同步连接引用
        self._async_ws = None        # websockets 异步连接引用（回退方案）
        self._event_loop = None      # 异步事件循环引用（回退方案）
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._connected = False
        self._connect_event = threading.Event()
        self._reconnect_count = 0
        self._need_reauth = False
        
        # ========== 订阅管理 ==========
        self._pending_subscriptions: List[Dict] = []
        self._active_subscriptions: List[Dict] = []
        self._sub_lock = threading.Lock()
        
        # ========== 订阅周期记录 ==========
        # 用户订阅的周期: {(symbol, period)} — 用于判断该不该回调
        self._user_periods: Set[Tuple[str, str]] = set()
        
        # ========== 统计 ==========
        self.stats = {
            'klines_received': 0,
            'history_received': 0,
            'reconnect_count': 0,
        }
    
    @property
    def connected(self) -> bool:
        """是否已连接"""
        return self._connected
    
    @property
    def _current_ws_url(self) -> str:
        return self.ws_urls[self._url_index % len(self.ws_urls)]
    
    def _notify_endpoint_connected(self):
        try:
            from ..data.auth_manager import set_active_endpoint_index
            set_active_endpoint_index(self._url_index)
        except Exception:
            pass
    
    def connect(self, timeout: float = 10.0) -> bool:
        """
        连接 data_server WebSocket（非阻塞）
        
        Args:
            timeout: 等待连接成功的超时时间（秒）
            
        Returns:
            是否连接成功
        """
        if not WEBSOCKET_AVAILABLE:
            print("[WSKlineClient] ❌ websocket-client 未安装")
            print("[WSKlineClient]    请运行: pip install websocket-client")
            return False
        
        if self._running:
            return self._connected
        
        self._running = True
        self._connect_event.clear()
        
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        
        success = self._connect_event.wait(timeout=timeout)
        if success:
            print(f"[WSKlineClient] ✅ 已连接 {self._current_ws_url}")
        else:
            print(f"[WSKlineClient] ⚠️ 连接超时 ({timeout}s)，将在后台继续重连")
        
        return success
    
    def subscribe_kline(self, symbol: str, period: str, preload: int = 100):
        """
        订阅K线数据（服务端聚合，直接订阅目标周期）
        
        服务端负责 1M → 目标周期的聚合，客户端只需订阅目标周期。
        
        Args:
            symbol: 合约代码（如 au888, rb888）
            period: K线周期（如 1M, 5M, 15M, 30M, 1H, 1D, 2M, 3M, 7M...）
            preload: 预加载历史K线数量，0表示不预加载
        """
        sym = symbol.lower()
        prd = period.upper()
        
        with self._sub_lock:
            self._user_periods.add((sym, prd))
            
            sub = {'symbol': sym, 'period': prd, 'preload': preload}
            self._active_subscriptions.append(sub)
            
            if self._connected:
                self._send_subscribe(sub)
            else:
                self._pending_subscriptions.append(sub)

    def refresh_history(
        self, symbol: str, period: str, preload: Optional[int] = None
    ) -> bool:
        """重新请求已有订阅的历史 K 线，不重复登记订阅。

        Args:
            symbol: 已订阅的合约代码。
            period: 已订阅的 K 线周期。
            preload: 本次请求数量；None 表示沿用原订阅数量。

        Returns:
            刷新请求是否已成功发送。
        """
        sym = symbol.lower()
        prd = period.upper()

        if preload is not None:
            if not isinstance(preload, int) or preload < 0:
                raise ValueError("preload 必须是大于等于 0 的整数或 None")

        with self._sub_lock:
            active = next(
                (
                    sub
                    for sub in self._active_subscriptions
                    if sub['symbol'] == sym and sub['period'] == prd
                ),
                None,
            )
            request = dict(active) if active is not None else None

        if request is None:
            print(f"[WSKlineClient] 未找到活动订阅: {sym} {prd}")
            return False
        if not self._connected:
            print(f"[WSKlineClient] 当前未连接，无法主动刷新: {sym} {prd}")
            return False

        if preload is not None:
            request['preload'] = preload

        sent = self._send_subscribe(request)
        if sent:
            print(
                f"[WSKlineClient] 已请求刷新历史数据: {sym} {prd} "
                f"x {request.get('preload', 0)}"
            )
        return sent
    
    def close(self):
        """断开连接"""
        self._running = False
        self.auto_reconnect = False
        
        if self._ws:
            try:
                self._ws.close()
            except:
                pass
        
        if self._thread:
            self._thread.join(timeout=3.0)
        
        self._connected = False
        print("[WSKlineClient] 已断开连接")
    
    # ========== 内部：连接管理 ==========
    
    def _run_loop(self):
        """后台运行循环（处理连接和重连）"""
        while self._running:
            if self._need_reauth and self.on_auth_required:
                print("[WSKlineClient] 服务端要求重新鉴权，正在重新验证...")
                try:
                    self.on_auth_required()
                    print("[WSKlineClient] 重新鉴权完成")
                except Exception as e:
                    print(f"[WSKlineClient] 重新鉴权失败: {e}")
                self._need_reauth = False
            
            try:
                self._do_connect()
            except Exception as e:
                if self._running:
                    print(f"[WSKlineClient] 连接异常: {e}")
            
            self._connected = False
            
            if not self._running:
                break
            
            if not self.auto_reconnect:
                break
            
            if self.max_reconnect_attempts > 0 and self._reconnect_count >= self.max_reconnect_attempts:
                print(f"[WSKlineClient] 达到最大重连次数 ({self.max_reconnect_attempts})，停止重连")
                break
            
            if len(self.ws_urls) > 1:
                self._url_index = (self._url_index + 1) % len(self.ws_urls)
                print(f"[WSKlineClient] 切换 data_server 地址 → {self._current_ws_url}")
            
            self._reconnect_count += 1
            self.stats['reconnect_count'] = self._reconnect_count
            print(f"[WSKlineClient] {self.reconnect_interval}s 后重连 (第{self._reconnect_count}次)...")
            
            for _ in range(int(self.reconnect_interval * 10)):
                if not self._running:
                    return
                time.sleep(0.1)
    
    def _do_connect(self):
        """执行一次WebSocket连接"""
        if websocket is None:
            self._do_connect_async()
            return
        
        # 使用 websocket-client（同步库，推荐）
        self._ws = websocket.WebSocketApp(
            self._current_ws_url,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_ws_error,
            on_close=self._on_close,
        )
        
        self._ws.run_forever(
            ping_interval=30,
            ping_timeout=10,
        )
    
    def _do_connect_async(self):
        """使用 websockets 异步库连接（回退方案）"""
        import asyncio
        import websockets as ws_lib
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._event_loop = loop
        
        async def _run():
            try:
                async with ws_lib.connect(
                    self._current_ws_url,
                    ping_interval=30,
                    ping_timeout=10,
                    close_timeout=5,
                    max_size=10 * 1024 * 1024,
                ) as ws:
                    self._async_ws = ws
                    self._connected = True
                    self.ws_url = self._current_ws_url
                    self._notify_endpoint_connected()
                    self._reconnect_count = 0
                    self._connect_event.set()
                    
                    is_reconnect = self._ever_connected
                    self._ever_connected = True
                    
                    if is_reconnect:
                        with self._sub_lock:
                            self._pending_subscriptions.clear()
                        await self._async_resend_all()
                    else:
                        await self._async_send_pending()
                    
                    if self.on_connected:
                        self.on_connected()
                    
                    async for message in ws:
                        if not self._running:
                            break
                        self._handle_message(message)
                        
            except ws_lib.exceptions.ConnectionClosedError as e:
                if getattr(e, 'code', None) == 4001:
                    self._need_reauth = True
                if self._running:
                    print(f"[WSKlineClient] async连接关闭: code={getattr(e, 'code', '?')}")
            except Exception as e:
                if self._running:
                    print(f"[WSKlineClient] async连接异常: {e}")
            finally:
                self._async_ws = None
        
        try:
            loop.run_until_complete(_run())
        finally:
            self._event_loop = None
            loop.close()
    
    async def _async_send_pending(self):
        """异步发送待订阅队列"""
        with self._sub_lock:
            for sub in self._pending_subscriptions:
                msg = json.dumps({
                    'action': 'subscribe_kline',
                    'symbol': sub['symbol'],
                    'period': sub['period'],
                    'preload': sub.get('preload', 0),
                })
                await self._async_ws.send(msg)
            self._pending_subscriptions.clear()
    
    async def _async_resend_all(self):
        """异步重发所有活跃订阅（重连恢复）"""
        with self._sub_lock:
            for sub in self._active_subscriptions:
                msg = json.dumps({
                    'action': 'subscribe_kline',
                    'symbol': sub['symbol'],
                    'period': sub['period'],
                    'preload': sub.get('preload', 0),
                })
                await self._async_ws.send(msg)
    
    # ========== 内部：WebSocket 事件处理 ==========
    
    def _on_open(self, ws):
        """WebSocket连接成功"""
        self._connected = True
        self.ws_url = self._current_ws_url
        self._notify_endpoint_connected()
        is_reconnect = self._ever_connected
        self._ever_connected = True
        self._reconnect_count = 0
        self._connect_event.set()
        
        if is_reconnect:
            print(f"[WSKlineClient] 重连成功，恢复 {len(self._active_subscriptions)} 个订阅")
            with self._sub_lock:
                self._pending_subscriptions.clear()
                for sub in self._active_subscriptions:
                    self._send_subscribe(sub)
        else:
            self._process_pending_subscriptions()
        
        if self.on_connected:
            try:
                self.on_connected()
            except Exception as e:
                print(f"[WSKlineClient] on_connected回调异常: {e}")
    
    def _on_message(self, ws, message: str):
        """收到WebSocket消息"""
        self._handle_message(message)
    
    def _on_ws_error(self, ws, error):
        """WebSocket错误"""
        if self._running:
            error_msg = str(error) if error else "未知错误"
            if 'Connection' not in error_msg:
                print(f"[WSKlineClient] WebSocket错误: {error_msg}")
            if self.on_error:
                try:
                    self.on_error(error_msg)
                except:
                    pass
    
    def _on_close(self, ws, close_status_code=None, close_msg=None):
        """WebSocket关闭"""
        self._connected = False
        if close_status_code == 4001:
            self._need_reauth = True
        if self.on_disconnected:
            try:
                self.on_disconnected()
            except:
                pass
    
    # ========== 核心：消息处理 ==========
    
    def _handle_message(self, message: str):
        """处理收到的消息"""
        try:
            data = json.loads(message)
            msg_type = data.get('type', '')
            
            if msg_type == 'welcome':
                pass
            
            elif msg_type == 'kline':
                self._handle_kline(data)
            
            elif msg_type == 'history':
                self._handle_history(data)
            
            elif msg_type == 'subscribed':
                symbol = data.get('symbol', '')
                period = data.get('period', '')
                preload = data.get('preload', 0)
                if (symbol, period) in self._user_periods:
                    print(f"[WSKlineClient] 订阅确认: {symbol} {period} (preload={preload})")
            
            elif msg_type == 'pong':
                pass
            
            elif msg_type == 'error':
                error_msg = data.get('message', '未知错误')
                print(f"[WSKlineClient] 服务器错误: {error_msg}")
            
        except json.JSONDecodeError:
            print(f"[WSKlineClient] 无效的JSON消息")
        except Exception as e:
            print(f"[WSKlineClient] 消息处理异常: {e}")
            import traceback
            traceback.print_exc()
    
    def _handle_kline(self, data: dict):
        """
        处理实时K线推送（服务端已完成聚合，直接回调）
        """
        symbol = data.get('symbol', '').lower()
        period = data.get('period', '').upper()
        kline_data = data.get('data', {})
        
        if not kline_data:
            return
        
        self.stats['klines_received'] += 1
        
        if (symbol, period) in self._user_periods and self.on_kline:
            try:
                self.on_kline(symbol, period, kline_data)
            except Exception as e:
                print(f"[WSKlineClient] on_kline({period})回调异常: {e}")
    
    def _handle_history(self, data: dict):
        """
        处理历史K线预加载
        
        历史数据来自服务端数据库（generate_history.py 生成的各周期数据）
        """
        symbol = data.get('symbol', '').lower()
        period = data.get('period', '').upper()
        klines = data.get('data', [])
        count = data.get('count', 0)
        
        # 只回调用户订阅的周期
        if (symbol, period) in self._user_periods and self.on_history:
            self.stats['history_received'] += count
            try:
                self.on_history(symbol, period, klines)
            except Exception as e:
                print(f"[WSKlineClient] on_history回调异常: {e}")
            
            print(f"[WSKlineClient] 收到历史数据: {symbol} {period} x {count}")
        else:
            # 内部 1M 订阅的历史数据（preload=0 不会有），静默跳过
            if count > 0:
                print(f"[WSKlineClient] 收到历史数据(内部): {symbol} {period} x {count}")
    
    # ========== 内部：发送 ==========
    
    def _send_subscribe(self, sub: Dict) -> bool:
        """发送订阅请求（支持同步和异步两种连接）。"""
        message = json.dumps({
            'action': 'subscribe_kline',
            'symbol': sub['symbol'],
            'period': sub['period'],
            'preload': sub.get('preload', 0),
        })
        
        try:
            if self._ws and hasattr(self._ws, 'send'):
                self._ws.send(message)
                return True
            elif self._async_ws and self._event_loop:
                import asyncio
                asyncio.run_coroutine_threadsafe(
                    self._async_ws.send(message),
                    self._event_loop
                )
                return True
        except Exception as e:
            print(f"[WSKlineClient] 发送订阅失败: {e}")
        return False
    
    def _process_pending_subscriptions(self):
        """处理待订阅队列"""
        with self._sub_lock:
            for sub in self._pending_subscriptions:
                self._send_subscribe(sub)
            self._pending_subscriptions.clear()
    
    def send_ping(self):
        """发送心跳"""
        if self._connected and self._ws:
            try:
                self._ws.send(json.dumps({'action': 'ping'}))
            except:
                pass
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        return {
            **self.stats,
            'connected': self._connected,
            'active_subscriptions': len(self._active_subscriptions),
            'user_periods': len(self._user_periods),
        }
