import pandas as pd
import numpy as np
from typing import Dict, List, Any, Optional, Union


class DataSource:
    """
    数据源类，用于管理单个数据源的数据和交易操作
    """
    
    def __init__(self, symbol: str, kline_period: str, adjust_type: str = '1'):
        """
        初始化数据源
        
        Args:
            symbol: 品种代码，如'rb888'
            kline_period: K线周期，如'1h', 'D'
            adjust_type: 复权类型，'0'表示不复权，'1'表示后复权
        """
        self.symbol = symbol
        self.kline_period = kline_period
        self.adjust_type = adjust_type
        self.data = pd.DataFrame()
        self.current_pos = 0
        self.target_pos = 0
        self.signal_reason = ""
        self.trades = []
        self.current_idx = 0
        self.current_price = None
        self.current_datetime = None
        self.pending_orders = []  # 存储待执行的订单
        
    def set_data(self, data: pd.DataFrame):
        """设置数据"""
        self.data = data
        
    def get_data(self) -> pd.DataFrame:
        """获取数据"""
        return self.data
        
    def get_current_price(self) -> Optional[float]:
        """获取当前价格"""
        if self.current_price is not None:
            return self.current_price
        if not self.data.empty and self.current_idx < len(self.data):
            return self.data.iloc[self.current_idx]['close']
        return None
        
    def get_current_datetime(self):
        """获取当前日期时间"""
        if self.current_datetime is not None:
            return self.current_datetime
        if not self.data.empty and self.current_idx < len(self.data):
            return self.data.index[self.current_idx]
        return None
        
    def get_current_pos(self) -> int:
        """获取当前持仓"""
        return self.current_pos
        
    def _update_pos(self, log_callback=None):
        """更新实际持仓"""
        if self.current_pos != self.target_pos:
            old_pos = self.current_pos
            self.current_pos = self.target_pos
            if log_callback:
                # 添加debug参数检查
                debug_mode = getattr(log_callback, 'debug_mode', True)
                if debug_mode:
                    log_callback(f"{self.symbol} {self.kline_period} 持仓变化: {old_pos} -> {self.current_pos}")
                
    def set_target_pos(self, target_pos: int, log_callback=None):
        """设置目标持仓"""
        self.target_pos = target_pos
        self._update_pos(log_callback)
        
    def set_signal_reason(self, reason: str):
        """设置交易信号原因"""
        self.signal_reason = reason
        
    def add_trade(self, action: str, price: float, volume: int, reason: str, datetime=None):
        """添加交易记录"""
        if datetime is None:
            datetime = self.get_current_datetime()
        
        self.trades.append({
            'datetime': datetime,
            'action': action,
            'price': price,
            'volume': volume,
            'reason': ''  # 不再记录原因
        })
        
    def get_price_by_type(self, order_type='bar_close'):
        """
        根据订单类型获取价格
        
        Args:
            order_type (str): 订单类型，可选值：
                - 'bar_close': 当前K线收盘价（默认）
                - 'next_bar_open': 下一K线开盘价
                - 'next_bar_close': 下一K线收盘价
                - 'next_bar_high': 下一K线最高价
                - 'next_bar_low': 下一K线最低价
                - 'market': 市价单，按对手价成交，买入按ask1，卖出按bid1
        
        Returns:
            float: 价格，如果无法获取则返回None
        """
        if not self.data.empty:
            if order_type == 'bar_close':
                if self.current_idx < len(self.data):
                    return self.data.iloc[self.current_idx]['close']
            elif order_type == 'next_bar_open':
                if self.current_idx + 1 < len(self.data) and 'open' in self.data.columns:
                    return self.data.iloc[self.current_idx + 1]['open']
            elif order_type == 'next_bar_close':
                if self.current_idx + 1 < len(self.data):
                    return self.data.iloc[self.current_idx + 1]['close']
            elif order_type == 'next_bar_high':
                if self.current_idx + 1 < len(self.data) and 'high' in self.data.columns:
                    return self.data.iloc[self.current_idx + 1]['high']
            elif order_type == 'next_bar_low':
                if self.current_idx + 1 < len(self.data) and 'low' in self.data.columns:
                    return self.data.iloc[self.current_idx + 1]['low']
            elif order_type == 'market':
                # 市价单，对于tick数据，可以使用买一卖一价格
                if self.current_idx < len(self.data):
                    if 'BidPrice1' in self.data.columns and 'AskPrice1' in self.data.columns:
                        # TICK数据：在具体的buy/sell方法中根据买卖方向确定价格
                        return None
                    else:
                        # K线数据：使用收盘价
                        return self.data.iloc[self.current_idx]['close']
        return None
        
    def _process_pending_orders(self, log_callback=None):
        """处理待执行的订单"""
        if not self.pending_orders:
            return
        
        # 获取debug模式设置
        debug_mode = getattr(log_callback, 'debug_mode', True) if log_callback else True
        
        orders_to_remove = []
        for i, order in enumerate(self.pending_orders):
            # 获取执行时间
            execution_time = order.get('execution_time', self.current_idx + 1)
            
            # 获取订单类型（默认为next_bar_open）
            order_type = order.get('order_type', 'next_bar_open')
            
            # 判断是否到达执行时间
            if execution_time <= self.current_idx:
                # 执行订单
                action = order['action']
                volume = order['volume']
                reason = order['reason']
                
                # 根据订单类型获取执行价格
                # 如果已经预先计算了价格，就使用那个价格
                if 'price' in order and order['price'] is not None:
                    price = order['price']
                else:
                    # 否则根据订单类型获取当前价格
                    price = self.get_price_by_type(order_type)
                    if price is None:
                        # 如果仍然无法获取价格，则使用当前价格
                        price = self.get_current_price()
                        if price is None:
                            # 如果完全无法获取价格，跳过此订单
                            continue
                
                # 更新持仓
                if action == "开多":
                    self.target_pos = self.current_pos + volume
                elif action == "平多":
                    if volume is None:
                        volume = max(0, self.current_pos)
                    # 检查是否有多头持仓可平
                    actual_volume = min(volume, max(0, self.current_pos))
                    if actual_volume <= 0:
                        # 没有多头持仓可平，跳过此订单
                        orders_to_remove.append(i)
                        continue
                    self.target_pos = self.current_pos - actual_volume
                    volume = actual_volume  # 更新volume为实际交易量
                elif action == "开空":
                    self.target_pos = self.current_pos - volume
                elif action == "平空":
                    if volume is None:
                        volume = max(0, -self.current_pos)
                    # 检查是否有空头持仓可平
                    actual_volume = min(volume, max(0, -self.current_pos))
                    if actual_volume <= 0:
                        # 没有空头持仓可平，跳过此订单
                        orders_to_remove.append(i)
                        continue
                    self.target_pos = self.current_pos + actual_volume
                    volume = actual_volume  # 更新volume为实际交易量
                elif action == "平多开空":  # 支持反手交易
                    self.target_pos = -self.current_pos  # 从多头变为空头
                elif action == "平空开多":  # 支持反手交易
                    self.target_pos = -self.current_pos  # 从空头变为多头
                
                # 更新持仓
                self._update_pos(log_callback)
                
                # 记录交易
                self.add_trade(action, price, volume, reason)
                
                if log_callback and debug_mode:
                    log_callback(f"{self.symbol} {self.kline_period} 执行订单: {action} {volume}手 成交价:{price:.2f} 类型:{order_type} 原因:{reason}")
                
                # 标记为待移除
                orders_to_remove.append(i)
        
        # 移除已执行的订单（从后往前移除，避免索引问题）
        for i in sorted(orders_to_remove, reverse=True):
            self.pending_orders.pop(i)
        
    def buy(self, volume: int = 1, reason: str = "", log_callback=None, order_type='bar_close', offset_ticks: Optional[int] = None, price: Optional[float] = None):
        """
        开多仓
        
        Args:
            volume (int): 交易数量
            reason (str): 交易原因
            log_callback: 日志回调函数
            order_type (str): 订单类型，可选值：
                - 'limit': 限价单（需指定price）
                - 'bar_close': 当前K线收盘价（默认）
                - 'next_bar_open': 下一K线开盘价
                - 'next_bar_close': 下一K线收盘价
                - 'next_bar_high': 下一K线最高价
                - 'next_bar_low': 下一K线最低价
                - 'market': 市价单，按ask1价格成交（买入用卖一价）
            offset_ticks: 价格偏移tick数
            price: 限价单价格（仅当order_type='limit'时有效）
        
        Returns:
            bool: 是否成功下单
        """
        # 获取debug模式设置
        debug_mode = getattr(log_callback, 'debug_mode', True) if log_callback else True
        
        if order_type == 'bar_close':
            # 当前K线收盘价下单，立即执行
            price = self.get_current_price()
            if price is None:
                return False
                
            self.target_pos = self.current_pos + volume
            if reason:
                self.set_signal_reason(reason)
            self._update_pos(log_callback)
            
            # 记录交易
            self.add_trade("开多", price, volume, reason)
            return True
        elif order_type == 'market':
            # 市价单，TICK数据买入使用卖一价格(AskPrice1)
            price = None
            if 'AskPrice1' in self.data.columns and self.current_idx < len(self.data):
                price = self.data.iloc[self.current_idx]['AskPrice1']
            else:
                price = self.get_current_price()
            
            if price is None:
                return False
                
            self.target_pos = self.current_pos + volume
            if reason:
                self.set_signal_reason(reason)
            self._update_pos(log_callback)
            
            # 记录交易
            self.add_trade("开多", price, volume, reason)
            
            if log_callback and debug_mode:
                log_callback(f"{self.symbol} {self.kline_period} 市价买入: {volume}手 成交价:{price:.2f} 原因:{reason}")
            
            return True
        else:
            # 下一K线价格下单，添加到待执行队列
            if price is None:
                price = self.get_price_by_type(order_type)
            
            # 注意：如果是next_bar_open/high/low/close，价格可能为None，因为下一K线的数据尚未加载
            # 但我们仍然可以添加到待执行队列，等待下一K线时执行，再根据order_type获取正确的价格
            
            # 添加到待执行队列
            self.pending_orders.append({
                'action': "开多",
                'volume': volume,
                'price': price,  # 可能为None，将在执行时重新获取
                'reason': reason,
                'order_type': order_type,  # 保存订单类型
                'execution_time': self.current_idx + 1  # 在下一K线执行
            })
            
            if log_callback and debug_mode:
                price_str = f"{price:.2f}" if price is not None else "待确定"
                log_callback(f"{self.symbol} {self.kline_period} 添加待执行订单: 开多 {volume}手 订单类型:{order_type} 预计价格:{price_str} 原因:{reason}")
            
            return True
        
    def sell(self, volume: Optional[int] = None, reason: str = "", log_callback=None, order_type='bar_close', offset_ticks: Optional[int] = None, price: Optional[float] = None):
        """
        平多仓
        
        Args:
            volume (int, optional): 交易数量，None表示平掉所有多仓
            reason (str): 交易原因
            log_callback: 日志回调函数
            order_type (str): 订单类型，可选值同buy函数
            offset_ticks: 价格偏移tick数
            price: 限价单价格（仅当order_type='limit'时有效）
        
        Returns:
            bool: 是否成功下单
        """
        # 获取debug模式设置
        debug_mode = getattr(log_callback, 'debug_mode', True) if log_callback else True
        
        if order_type == 'bar_close':
            # 当前K线收盘价下单，立即执行
            price = self.get_current_price()
            if price is None:
                return False
                
            if volume is None:
                volume = max(0, self.current_pos)
            
            # 检查是否有多头持仓可平
            actual_volume = min(volume, max(0, self.current_pos))
            if actual_volume <= 0:
                # 没有多头持仓可平，不记录交易
                if log_callback and debug_mode:
                    log_callback(f"{self.symbol} {self.kline_period} 平多失败: 无多头持仓可平")
                return True
                
            self.target_pos = self.current_pos - actual_volume
            if reason:
                self.set_signal_reason(reason)
            self._update_pos(log_callback)
            
            # 记录交易
            self.add_trade("平多", price, actual_volume, reason)
            return True
        elif order_type == 'market':
            # 市价单，TICK数据卖出使用买一价格(BidPrice1)
            price = None
            if 'BidPrice1' in self.data.columns and self.current_idx < len(self.data):
                price = self.data.iloc[self.current_idx]['BidPrice1']
            else:
                price = self.get_current_price()
            
            if price is None:
                return False
                
            if volume is None:
                volume = max(0, self.current_pos)
            
            # 检查是否有多头持仓可平
            actual_volume = min(volume, max(0, self.current_pos))
            if actual_volume <= 0:
                # 没有多头持仓可平，不记录交易
                if log_callback and debug_mode:
                    log_callback(f"{self.symbol} {self.kline_period} 市价平多失败: 无多头持仓可平")
                return True
                
            self.target_pos = self.current_pos - actual_volume
            if reason:
                self.set_signal_reason(reason)
            self._update_pos(log_callback)
            
            # 记录交易
            self.add_trade("平多", price, actual_volume, reason)
            
            if log_callback and debug_mode:
                log_callback(f"{self.symbol} {self.kline_period} 市价卖出: {actual_volume}手 成交价:{price:.2f} 原因:{reason}")
            
            return True
        else:
            # 下一K线价格下单，添加到待执行队列
            if price is None:
                price = self.get_price_by_type(order_type)
            # 注意：如果是next_bar_open/high/low/close，价格可能为None，因为下一K线的数据尚未加载
            
            if volume is None:
                volume = max(0, self.current_pos)
            
            # 检查是否有多头持仓可平
            actual_volume = min(volume, max(0, self.current_pos))
            if actual_volume <= 0:
                # 没有多头持仓可平，不添加订单
                if log_callback and debug_mode:
                    log_callback(f"{self.symbol} {self.kline_period} 平多订单失败: 无多头持仓可平")
                return True
            
            # 添加到待执行队列
            self.pending_orders.append({
                'action': "平多",
                'volume': actual_volume,
                'price': price,  # 可能为None，将在执行时重新获取
                'reason': reason,
                'order_type': order_type,  # 保存订单类型
                'execution_time': self.current_idx + 1  # 在下一K线执行
            })
            
            if log_callback and debug_mode:
                price_str = f"{price:.2f}" if price is not None else "待确定"
                log_callback(f"{self.symbol} {self.kline_period} 添加待执行订单: 平多 {actual_volume}手 订单类型:{order_type} 预计价格:{price_str} 原因:{reason}")
            
            return True
        
    def sellshort(self, volume: int = 1, reason: str = "", log_callback=None, order_type='bar_close', offset_ticks: Optional[int] = None, price: Optional[float] = None):
        """
        开空仓
        
        Args:
            volume (int): 交易数量
            reason (str): 交易原因
            log_callback: 日志回调函数
            order_type (str): 订单类型，可选值同buy函数
            offset_ticks: 价格偏移tick数
            price: 限价单价格（仅当order_type='limit'时有效）
        
        Returns:
            bool: 是否成功下单
        """
        # 获取debug模式设置
        debug_mode = getattr(log_callback, 'debug_mode', True) if log_callback else True
        
        if order_type == 'bar_close':
            # 当前K线收盘价下单，立即执行
            price = self.get_current_price()
            if price is None:
                return False
                
            self.target_pos = self.current_pos - volume
            if reason:
                self.set_signal_reason(reason)
            self._update_pos(log_callback)
            
            # 记录交易
            self.add_trade("开空", price, volume, reason)
            return True
        elif order_type == 'market':
            # 市价单，TICK数据卖出使用买一价格(BidPrice1)
            price = None
            if 'BidPrice1' in self.data.columns and self.current_idx < len(self.data):
                price = self.data.iloc[self.current_idx]['BidPrice1']
            else:
                price = self.get_current_price()
            
            if price is None:
                return False
                
            self.target_pos = self.current_pos - volume
            if reason:
                self.set_signal_reason(reason)
            self._update_pos(log_callback)
            
            # 记录交易
            self.add_trade("开空", price, volume, reason)
            
            if log_callback and debug_mode:
                log_callback(f"{self.symbol} {self.kline_period} 市价卖空: {volume}手 成交价:{price:.2f} 原因:{reason}")
            
            return True
        else:
            # 下一K线价格下单，添加到待执行队列
            if price is None:
                price = self.get_price_by_type(order_type)
            # 注意：如果是next_bar_open/high/low/close，价格可能为None，因为下一K线的数据尚未加载
            
            # 添加到待执行队列
            self.pending_orders.append({
                'action': "开空",
                'volume': volume,
                'price': price,  # 可能为None，将在执行时重新获取
                'reason': reason,
                'order_type': order_type,  # 保存订单类型
                'execution_time': self.current_idx + 1  # 在下一K线执行
            })
            
            if log_callback and debug_mode:
                price_str = f"{price:.2f}" if price is not None else "待确定"
                log_callback(f"{self.symbol} {self.kline_period} 添加待执行订单: 开空 {volume}手 订单类型:{order_type} 预计价格:{price_str} 原因:{reason}")
            
            return True
        
    def buycover(self, volume: Optional[int] = None, reason: str = "", log_callback=None, order_type='bar_close', offset_ticks: Optional[int] = None, price: Optional[float] = None):
        """
        平空仓
        
        Args:
            volume (int, optional): 交易数量，None表示平掉所有空仓
            reason (str): 交易原因
            log_callback: 日志回调函数
            order_type (str): 订单类型，可选值同buy函数
            offset_ticks: 价格偏移tick数
            price: 限价单价格（仅当order_type='limit'时有效）
        
        Returns:
            bool: 是否成功下单
        """
        # 获取debug模式设置
        debug_mode = getattr(log_callback, 'debug_mode', True) if log_callback else True
        
        if order_type == 'bar_close':
            # 当前K线收盘价下单，立即执行
            price = self.get_current_price()
            if price is None:
                return False
                
            if volume is None:
                volume = max(0, -self.current_pos)
            
            # 检查是否有空头持仓可平
            actual_volume = min(volume, max(0, -self.current_pos))
            if actual_volume <= 0:
                # 没有空头持仓可平，不记录交易
                if log_callback and debug_mode:
                    log_callback(f"{self.symbol} {self.kline_period} 平空失败: 无空头持仓可平")
                return True
                
            self.target_pos = self.current_pos + actual_volume
            if reason:
                self.set_signal_reason(reason)
            self._update_pos(log_callback)
            
            # 记录交易
            self.add_trade("平空", price, actual_volume, reason)
            return True
        elif order_type == 'market':
            # 市价单，TICK数据买入使用卖一价格(AskPrice1)
            price = None
            if 'AskPrice1' in self.data.columns and self.current_idx < len(self.data):
                price = self.data.iloc[self.current_idx]['AskPrice1']
            else:
                price = self.get_current_price()
            
            if price is None:
                return False
                
            if volume is None:
                volume = max(0, -self.current_pos)
            
            # 检查是否有空头持仓可平
            actual_volume = min(volume, max(0, -self.current_pos))
            if actual_volume <= 0:
                # 没有空头持仓可平，不记录交易
                if log_callback and debug_mode:
                    log_callback(f"{self.symbol} {self.kline_period} 市价平空失败: 无空头持仓可平")
                return True
                
            self.target_pos = self.current_pos + actual_volume
            if reason:
                self.set_signal_reason(reason)
            self._update_pos(log_callback)
            
            # 记录交易
            self.add_trade("平空", price, actual_volume, reason)
            
            if log_callback and debug_mode:
                log_callback(f"{self.symbol} {self.kline_period} 市价买平: {actual_volume}手 成交价:{price:.2f} 原因:{reason}")
            
            return True
        else:
            # 下一K线价格下单，添加到待执行队列
            if price is None:
                price = self.get_price_by_type(order_type)
            # 注意：如果是next_bar_open/high/low/close，价格可能为None，因为下一K线的数据尚未加载
            
            if volume is None:
                volume = max(0, -self.current_pos)
            
            # 检查是否有空头持仓可平
            actual_volume = min(volume, max(0, -self.current_pos))
            if actual_volume <= 0:
                # 没有空头持仓可平，不添加订单
                if log_callback and debug_mode:
                    log_callback(f"{self.symbol} {self.kline_period} 平空订单失败: 无空头持仓可平")
                return True
            
            # 添加到待执行队列
            self.pending_orders.append({
                'action': "平空",
                'volume': actual_volume,
                'price': price,  # 可能为None，将在执行时重新获取
                'reason': reason,
                'order_type': order_type,  # 保存订单类型
                'execution_time': self.current_idx + 1  # 在下一K线执行
            })
            
            if log_callback and debug_mode:
                price_str = f"{price:.2f}" if price is not None else "待确定"
                log_callback(f"{self.symbol} {self.kline_period} 添加待执行订单: 平空 {actual_volume}手 订单类型:{order_type} 预计价格:{price_str} 原因:{reason}")
            
            return True
        
    def reverse_pos(self, reason: str = "", log_callback=None, order_type='bar_close'):
        """
        反手（多转空，空转多）
        
        Args:
            reason (str): 交易原因
            log_callback: 日志回调函数
            order_type (str): 订单类型，可选值同buy函数
        
        Returns:
            bool: 是否成功下单
        """
        # 获取debug模式设置
        debug_mode = getattr(log_callback, 'debug_mode', True) if log_callback else True
        
        old_pos = self.current_pos
        
        if order_type == 'bar_close':
            # 当前K线收盘价下单，立即执行
            price = self.get_current_price()
            if price is None:
                return False
                
            self.target_pos = -old_pos
            if reason:
                self.set_signal_reason(reason)
            self._update_pos(log_callback)
            
            # 记录交易
            if old_pos > 0:
                self.add_trade("平多开空", price, old_pos, reason)
            elif old_pos < 0:
                self.add_trade("平空开多", price, -old_pos, reason)
                
            return True
        elif order_type == 'market':
            # 市价单，TICK数据使用对应价格
            price = None
            
            # 不同持仓方向使用不同的价格
            if old_pos > 0:  # 平多开空，卖出用买一价格(BidPrice1)
                if 'BidPrice1' in self.data.columns and self.current_idx < len(self.data):
                    price = self.data.iloc[self.current_idx]['BidPrice1']
                else:
                    price = self.get_current_price()
            elif old_pos < 0:  # 平空开多，买入用卖一价格(AskPrice1)
                if 'AskPrice1' in self.data.columns and self.current_idx < len(self.data):
                    price = self.data.iloc[self.current_idx]['AskPrice1']
                else:
                    price = self.get_current_price()
            else:
                return True  # 无持仓，无需反手
            
            if price is None:
                return False
                
            self.target_pos = -old_pos
            if reason:
                self.set_signal_reason(reason)
            self._update_pos(log_callback)
            
            # 记录交易
            if old_pos > 0:
                self.add_trade("平多开空", price, old_pos, reason)
                if log_callback and debug_mode:
                    log_callback(f"{self.symbol} {self.kline_period} 市价反手: 平多开空 {old_pos}手 成交价:{price:.2f} 原因:{reason}")
            elif old_pos < 0:
                self.add_trade("平空开多", price, -old_pos, reason)
                if log_callback and debug_mode:
                    log_callback(f"{self.symbol} {self.kline_period} 市价反手: 平空开多 {-old_pos}手 成交价:{price:.2f} 原因:{reason}")
                
            return True
        else:
            # 下一K线价格下单，添加到待执行队列
            price = self.get_price_by_type(order_type)
            # 注意：如果是next_bar_open/high/low/close，价格可能为None，将在执行时获取
            
            # 添加到待执行队列
            if old_pos > 0:
                action = "平多开空"
                volume = old_pos
            elif old_pos < 0:
                action = "平空开多"
                volume = -old_pos
            else:
                return True  # 无持仓，无需反手
            
            self.pending_orders.append({
                'action': action,
                'volume': volume,
                'price': price,  # 可能为None，将在执行时重新获取
                'reason': reason,
                'order_type': order_type,  # 保存订单类型
                'execution_time': self.current_idx + 1  # 在下一K线执行
            })
            
            if log_callback and debug_mode:
                price_str = f"{price:.2f}" if price is not None else "待确定"
                log_callback(f"{self.symbol} {self.kline_period} 添加待执行订单: {action} {volume}手 订单类型:{order_type} 预计价格:{price_str} 原因:{reason}")
            
            return True
        
    def close_all(self, reason: str = "", log_callback=None, order_type='bar_close'):
        """
        平掉所有持仓
        
        Args:
            reason (str): 交易原因
            log_callback: 日志回调函数
            order_type (str): 订单类型，可选值同buy函数
        
        Returns:
            bool: 是否成功下单
        """
        # 获取debug模式设置
        debug_mode = getattr(log_callback, 'debug_mode', True) if log_callback else True
        
        if self.current_pos > 0:
            # 平多仓
            if order_type == 'market':
                # 市价单，TICK数据卖出使用买一价格(BidPrice1)
                price = None
                if 'BidPrice1' in self.data.columns and self.current_idx < len(self.data):
                    price = self.data.iloc[self.current_idx]['BidPrice1']
                else:
                    price = self.get_current_price()
                
                if price is None:
                    return False
                    
                volume = self.current_pos
                self.target_pos = 0
                if reason:
                    self.set_signal_reason(reason)
                self._update_pos(log_callback)
                
                # 记录交易
                self.add_trade("平多", price, volume, reason)
                
                if log_callback and debug_mode:
                    log_callback(f"{self.symbol} {self.kline_period} 市价平仓: 平多 {volume}手 成交价:{price:.2f} 原因:{reason}")
                
                return True
            else:
                return self.sell(volume=None, reason=reason, log_callback=log_callback, order_type=order_type)
        elif self.current_pos < 0:
            # 平空仓
            if order_type == 'market':
                # 市价单，TICK数据买入使用卖一价格(AskPrice1)
                price = None
                if 'AskPrice1' in self.data.columns and self.current_idx < len(self.data):
                    price = self.data.iloc[self.current_idx]['AskPrice1']
                else:
                    price = self.get_current_price()
                
                if price is None:
                    return False
                    
                volume = -self.current_pos
                self.target_pos = 0
                if reason:
                    self.set_signal_reason(reason)
                self._update_pos(log_callback)
                
                # 记录交易
                self.add_trade("平空", price, volume, reason)
                
                if log_callback and debug_mode:
                    log_callback(f"{self.symbol} {self.kline_period} 市价平仓: 平空 {volume}手 成交价:{price:.2f} 原因:{reason}")
                
                return True
            else:
                return self.buycover(volume=None, reason=reason, log_callback=log_callback, order_type=order_type)
        return True  # 已经没有持仓
    
    # 数据访问方法
    def get_close(self) -> pd.Series:
        """获取收盘价序列"""
        df = self.get_klines()
        return df['close'] if 'close' in df.columns else pd.Series(dtype=float)  # type: ignore
    
    def get_open(self) -> pd.Series:
        """获取开盘价序列"""
        df = self.get_klines()
        return df['open'] if 'open' in df.columns else pd.Series(dtype=float)  # type: ignore
    
    def get_high(self) -> pd.Series:
        """获取最高价序列"""
        df = self.get_klines()
        return df['high'] if 'high' in df.columns else pd.Series(dtype=float)  # type: ignore
    
    def get_low(self) -> pd.Series:
        """获取最低价序列"""
        df = self.get_klines()
        return df['low'] if 'low' in df.columns else pd.Series(dtype=float)  # type: ignore
        
    def get_volume(self) -> pd.Series:
        """获取成交量序列"""
        df = self.get_klines()
        return df['volume'] if 'volume' in df.columns else pd.Series(dtype=float)  # type: ignore
        
    def get_klines(self) -> pd.DataFrame:
        """
        获取K线数据
        
        回测模式：返回从开始到当前索引的数据（避免未来数据泄露）
        实盘模式：返回所有缓存的数据（deque滚动窗口）
        """
        if not self.data.empty and hasattr(self, 'current_idx'):
            # 回测模式：只返回到当前索引的数据
            return self.data.iloc[:self.current_idx + 1]
        # 实盘模式或无索引：返回所有数据
        return self.data

    def get_tick(self) -> Optional[pd.Series]:
        """返回当前tick的所有字段（Series）"""
        if not self.data.empty and self.current_idx < len(self.data):
            return self.data.iloc[self.current_idx]
        return None

    def get_ticks(self, window: int = 100) -> pd.DataFrame:
        """返回最近window条tick数据（DataFrame）"""
        if not self.data.empty and self.current_idx < len(self.data):
            start = max(0, self.current_idx - window + 1)
            return self.data.iloc[start:self.current_idx+1]
        return pd.DataFrame()


class MultiDataSource:
    """
    多数据源管理类，用于管理多个数据源
    """
    
    def __init__(self):
        """初始化多数据源管理器"""
        self.data_sources = []
        self.log_callback = None
        
    def set_log_callback(self, callback):
        """设置日志回调函数"""
        self.log_callback = callback
        
    def add_data_source(self, symbol: str, kline_period: str, adjust_type: str = '1', data: Optional[pd.DataFrame] = None) -> int:
        """
        添加数据源
        
        Args:
            symbol: 品种代码，如'rb888'
            kline_period: K线周期，如'1h', 'D'
            adjust_type: 复权类型，'0'表示不复权，'1'表示后复权
            data: 数据，如果为None则创建空数据源
            
        Returns:
            数据源索引
        """
        data_source = DataSource(symbol, kline_period, adjust_type)
        if data is not None:
            data_source.set_data(data)
        self.data_sources.append(data_source)
        return len(self.data_sources) - 1
        
    def get_data_source(self, index: int) -> Optional[DataSource]:
        """获取指定索引的数据源"""
        if 0 <= index < len(self.data_sources):
            return self.data_sources[index]
        return None
        
    def get_data_sources_count(self) -> int:
        """获取数据源数量"""
        return len(self.data_sources)
        
    def __getitem__(self, index: int) -> Optional[DataSource]:
        """通过索引访问数据源"""
        return self.get_data_source(index)
        
    def __len__(self) -> int:
        """获取数据源数量"""
        return self.get_data_sources_count()
        
    def align_data(self, align_index: bool = True, fill_method: str = 'ffill'):
        """
        对齐所有数据源的数据
        
        Args:
            align_index: 是否对齐索引
            fill_method: 填充方法，可选值：'ffill', 'bfill', None
        """
        if len(self.data_sources) <= 1:
            return  # 只有一个或没有数据源，不需要对齐
            
        # 收集所有数据源的索引
        all_indices = []
        for ds in self.data_sources:
            if not ds.data.empty:
                all_indices.append(ds.data.index)
                
        if not all_indices:
            return  # 没有有效的数据源
            
        # 找到共同的索引范围
        common_index = all_indices[0]
        for idx in all_indices[1:]:
            common_index = common_index.union(idx)
            
        # 对齐所有数据源的数据
        for ds in self.data_sources:
            if not ds.data.empty:
                # 重新索引数据
                ds.data = ds.data.reindex(common_index)
                
                # 填充缺失值
                if fill_method:
                    if fill_method == 'ffill':
                        ds.data = ds.data.ffill()
                    elif fill_method == 'bfill':
                        ds.data = ds.data.bfill()
                    else:
                        ds.data = ds.data.fillna(method=fill_method)  # 保留兼容性 