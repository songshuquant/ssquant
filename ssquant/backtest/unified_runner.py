#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
统一策略运行器
支持历史回测、SIMNOW模拟交易、实盘交易三种模式
实现"一次编写，多处运行"的策略开发模式
"""

import time
import pandas as pd
from datetime import datetime
from typing import Dict, List, Any, Optional, Callable
from enum import Enum

from .backtest_core import MultiSourceBacktester
from ..api.strategy_api import create_strategy_api


class RunMode(Enum):
    """运行模式枚举"""
    BACKTEST = "backtest"           # 历史回测
    SIMNOW = "simnow"               # SIMNOW模拟交易
    REAL_TRADING = "real_trading"   # 实盘交易


class UnifiedStrategyRunner:
    """
    统一策略运行器
    
    支持三种运行模式：
    1. 历史数据回测
    2. SIMNOW模拟交易
    3. 实盘CTP交易
    
    使用示例：
        runner = UnifiedStrategyRunner(mode=RunMode.BACKTEST)
        runner.set_config({...})
        results = runner.run(strategy_func, initialize_func, params)
    """
    
    def __init__(self, mode: RunMode = RunMode.BACKTEST):
        """
        初始化统一策略运行器
        
        Args:
            mode: 运行模式
        """
        self.mode = mode
        self.config = {}
        self.strategy_func = None
        self.initialize_func = None
        self.strategy_params = {}
        
        # 各模式的运行器
        self.backtester = None
        self.live_runner = None
        
        print(f"[统一运行器] 初始化 - 模式: {mode.value}")
    
    def _print_disclaimer(self):
        """打印品牌信息与免责声明"""
        border = "=" * 80
        print(f"\n{border}")
        print("  🐿️  松鼠Quant (SSQuant) - 专业量化交易框架")
        print(f"{border}")
        print("  🌐 官方网站: quant789.com")
        print("  📱 公众号  : 松鼠Quant")
        print(f"{border}")
        print("  ⚠️  风险提示 & 免责声明:")
        print("  1. 期货交易具有高风险，可能导致本金全部损失。")
        print("  2. 本软件仅供学习、研究与策略开发使用，不构成任何投资建议，且不能保证框架无BUG。")
        print("  3. 历史回测业绩不代表未来表现，模拟盘盈利不代表实盘盈利。")
        print("  4. 使用本软件产生的任何交易盈亏由用户自行承担，开发者不承担任何责任。")
        print("  5. 若不同意以上条款，请立即停止使用并退出！")
        print(f"{border}\n")

    def set_config(self, config: Dict[str, Any]):
        """
        设置配置
        
        Args:
            config: 配置字典，根据不同模式需要不同参数
                
                回测模式必填:
                    - symbol: 合约代码
                    - kline_period: K线周期
                    - 以下三种数据请求方式至少选一种:
                      a) start_date + end_date: 日期范围 (如 '2025-01-01', '2026-01-31')
                      b) start_time + end_time: 精确时间范围 (如 '2026-02-11 09:00:00')
                      c) limit: BAR线数量 (如 500，获取最近500根K线)
                    
                SIMNOW/实盘模式必填:
                    - investor_id: 账号
                    - password: 密码
                    - symbol: 合约代码
                    
                SIMNOW额外参数:
                    - server_name: 服务器名称 (默认: "24hour")
                    
                实盘额外参数:
                    - broker_id: 期货公司代码
                    - md_server: 行情服务器
                    - td_server: 交易服务器
                    - app_id: AppID
                    - auth_code: 授权码
                    
                通用可选参数:
                    - initial_capital: 初始资金
                    - commission: 手续费率
                    - margin_rate: 保证金率
                    - contract_multiplier: 合约乘数
                    - enable_data_recording: 是否启用数据落盘 (默认: False)
                    - data_recording_path: 数据落盘路径
        """
        self.config = config
        
        # 验证配置
        self._validate_config()
        
        return self
    
    def _validate_config(self):
        """验证配置"""
        if self.mode == RunMode.BACKTEST:
            # 支持三种数据请求方式:
            #   1. 日期范围: start_date + end_date
            #   2. 精确时间: start_time + end_time
            #   3. BAR线数量: limit
            # start_date/end_date 在提供 limit 或 start_time/end_time 时不再强制
            has_date_range = 'start_date' in self.config and 'end_date' in self.config
            has_time_range = 'start_time' in self.config or 'end_time' in self.config
            has_limit = 'limit' in self.config
            has_data_query = has_date_range or has_time_range or has_limit
            
            if 'data_sources' in self.config:
                # 多数据源模式
                required = ['data_sources']
                if not has_data_query:
                    required.extend(['start_date', 'end_date'])
            else:
                # 单数据源模式
                required = ['symbol', 'kline_period']
                if not has_data_query:
                    required.extend(['start_date', 'end_date'])
            missing = [key for key in required if key not in self.config]
            if missing:
                raise ValueError(f"回测模式缺少必填参数: {missing}")
        
        elif self.mode == RunMode.SIMNOW:
            # 支持单数据源和多数据源两种配置方式
            if 'data_sources' in self.config:
                # 多数据源模式
                required = ['investor_id', 'password', 'data_sources']
            else:
                # 单数据源模式
                required = ['investor_id', 'password', 'symbol']
            missing = [key for key in required if key not in self.config]
            if missing:
                raise ValueError(f"SIMNOW模式缺少必填参数: {missing}")
        
        elif self.mode == RunMode.REAL_TRADING:
            # 支持单数据源和多数据源两种配置方式
            if 'data_sources' in self.config:
                # 多数据源模式
                required = ['broker_id', 'investor_id', 'password', 'md_server', 
                           'td_server', 'app_id', 'auth_code', 'data_sources']
            else:
                # 单数据源模式
                required = ['broker_id', 'investor_id', 'password', 'md_server', 
                           'td_server', 'app_id', 'auth_code', 'symbol']
            missing = [key for key in required if key not in self.config]
            if missing:
                raise ValueError(f"实盘模式缺少必填参数: {missing}")
    
    def run(self, strategy: Callable, initialize: Optional[Callable] = None, 
            strategy_params: Optional[Dict] = None,
            on_trade: Optional[Callable] = None,
            on_order: Optional[Callable] = None,
            on_cancel: Optional[Callable] = None,
            on_order_error: Optional[Callable] = None,
            on_cancel_error: Optional[Callable] = None,
            on_account: Optional[Callable] = None,
            on_position: Optional[Callable] = None,
            on_position_complete: Optional[Callable] = None,
            on_disconnect: Optional[Callable] = None,
            on_query_trade: Optional[Callable] = None,
            on_query_trade_complete: Optional[Callable] = None,
            on_query_order: Optional[Callable] = None,
            on_query_order_complete: Optional[Callable] = None) -> Dict[str, Any]:
        """
        运行策略
        
        Args:
            strategy: 策略函数
            initialize: 初始化函数
            strategy_params: 策略参数
            
            以下回调仅实盘模式(SIMNOW/REAL_TRADING)有效:
            on_trade: 成交回调 - 订单成交时触发
            on_order: 报单回调 - 报单状态变化时触发
            on_cancel: 撤单回调 - 订单被撤销时触发
            on_order_error: 报单错误回调 - 报单失败时触发
            on_cancel_error: 撤单错误回调 - 撤单失败时触发
            on_account: 账户资金回调 - 资金变化时触发
            on_position: 持仓回调 - 持仓变化时触发
            on_position_complete: 持仓查询完成回调 - 持仓查询完成时触发
            on_disconnect: 断开连接回调 - 与CTP服务器断开时触发
            on_query_trade: 成交查询回调 - 查询成交记录时触发（单条）
            on_query_trade_complete: 成交查询完成回调 - 查询成交完成时触发
            on_query_order: 委托查询回调 - 查询委托记录时触发（单条）
            on_query_order_complete: 委托查询完成回调 - 查询委托完成时触发
            
        Returns:
            运行结果字典
        """
        self.strategy_func = strategy
        self.initialize_func = initialize
        self.strategy_params = strategy_params or {}
        self.on_trade_callback = on_trade
        self.on_order_callback = on_order
        self.on_cancel_callback = on_cancel
        self.on_order_error_callback = on_order_error
        self.on_cancel_error_callback = on_cancel_error
        self.on_account_callback = on_account
        self.on_position_callback = on_position
        self.on_position_complete_callback = on_position_complete
        self.on_disconnect_callback = on_disconnect
        self.on_query_trade_callback = on_query_trade
        self.on_query_trade_complete_callback = on_query_trade_complete
        self.on_query_order_callback = on_query_order
        self.on_query_order_complete_callback = on_query_order_complete
        
        print(f"\n{'='*80}")
        print(f"运行模式: {self.mode.value}")
        print(f"{'='*80}\n")
        
        if self.mode == RunMode.BACKTEST:
            return self._run_backtest()
        elif self.mode == RunMode.SIMNOW:
            return self._run_simnow()
        elif self.mode == RunMode.REAL_TRADING:
            return self._run_real_trading()
        else:
            raise ValueError(f"不支持的运行模式: {self.mode}")
    
    def _run_backtest(self) -> Dict[str, Any]:
        """运行历史回测"""
        from ..config.trading_config import get_api_auth
        API_USERNAME, API_PASSWORD = get_api_auth()

        data_source_mode = self.config.get('data_source_mode', 'data_server')
        is_local_mode = data_source_mode == 'local'

        # 远程模式下进行鉴权检查；本地模式跳过，避免 verify_auth() 缓存污染
        if not is_local_mode:
            from ..data.auth_manager import verify_auth, get_auth_message, set_effective_data_server
            set_effective_data_server(self.config.get('data_server'))
            if not verify_auth():
                auth_msg = get_auth_message()
                raise RuntimeError(
                    f"\n{'='*70}\n"
                    f"【当前数据模式: data_server】需要松鼠俱乐部会员账号才能从远程服务器拉取数据。\n"
                    f"鉴权失败原因: {auth_msg}\n"
                    f"{'='*70}\n"
                    f"\n解决方案（二选一）:\n"
                    f"\n1) 申请俱乐部会员并配置账号:\n"
                    f"   联系小松鼠 微信: viquant01\n"
                    f"   然后在 ssquant/config/trading_config.py 中填写俱乐部账号(API_USERNAME)和俱乐部密码(API_PASSWORD)\n"
                    f"\n2) 切换到本地数据模式（无需会员）:\n"
                    f"   在 get_config() 中将参数改为: data_source_mode='local'\n"
                    f"   并确保已使用 examples/A_工具_导入数据库DB示例.py\n"
                    f"   将数据导入 data_cache/backtest_data.db\n"
                    f"{'='*70}"
                )
        
        # 创建回测器
        self.backtester = MultiSourceBacktester()

        # 回测账户初始资金（支持两种分配模式）：
        # 模式1 - 绝对金额：每个 DS 设置 initial_capital，按品种去重求和
        # 模式2 - 比例权重：每个 DS 设置 capital_ratio，基于顶层 initial_capital 按权重分配
        #   capital_ratio 按数据源独立分配（同品种不同周期可设不同权重）
        top_level_capital = self.config.get('initial_capital', 100000)
        _resolved_symbol_capitals = {}  # {symbol: 品种级 initial_capital，用于 symbol_config}
        _per_ds_capitals = None         # 按 DS 顺序的资金列表，ratio 模式下有效
        total_initial_capital = 0

        if 'data_sources' in self.config:
            _has_ratio = any('capital_ratio' in ds for ds in self.config['data_sources'])

            if _has_ratio:
                # 比例模式：每个 DS 独立权重，未指定的默认 1.0
                _ds_ratios = []
                for ds_config in self.config['data_sources']:
                    _ds_ratios.append(float(ds_config.get('capital_ratio', 1.0)))
                total_ratio = sum(_ds_ratios)
                _per_ds_capitals = [top_level_capital * r / total_ratio for r in _ds_ratios]
                total_initial_capital = top_level_capital
                # 按品种汇总（用于 symbol_config 的 initial_capital 字段）
                for ds_config, ds_cap in zip(self.config['data_sources'], _per_ds_capitals):
                    sym = ds_config['symbol']
                    _resolved_symbol_capitals[sym] = _resolved_symbol_capitals.get(sym, 0) + ds_cap
                # 打印分配结果
                print(f"\n[资金分配] 总资金 {top_level_capital:,.0f} 元，按 capital_ratio 分配：")
                for ds_config, ds_cap, ratio in zip(self.config['data_sources'], _per_ds_capitals, _ds_ratios):
                    pct = ratio / total_ratio * 100
                    print(f"  {ds_config['symbol']} {ds_config.get('kline_period',''):>4s}  "
                          f"权重 {ratio:g}  →  {pct:5.1f}%  →  {ds_cap:>10,.0f} 元")
                print()
            else:
                # 绝对金额模式（原有逻辑）
                for ds_config in self.config['data_sources']:
                    sym = ds_config['symbol']
                    _resolved_symbol_capitals[sym] = ds_config.get(
                        'initial_capital', top_level_capital
                    )
                total_initial_capital = sum(_resolved_symbol_capitals.values()) or top_level_capital
        else:
            total_initial_capital = top_level_capital
        
        # 设置基础配置
        lookback_bars = self.config.get('lookback_bars', 500)
        _base_cfg = {
            'username': API_USERNAME,
            'password': API_PASSWORD,
            'use_cache': self.config.get('use_cache', True),
            'save_data': self.config.get('save_data', True),
            'align_data': self.config.get('align_data', False),
            'fill_method': self.config.get('fill_method', 'ffill'),
            'lookback_bars': lookback_bars,
            'debug': self.config.get('debug', False),
            'initial_capital': total_initial_capital,
            'data_source_mode': data_source_mode,
        }
        if _per_ds_capitals is not None:
            _base_cfg['_per_ds_capitals'] = _per_ds_capitals
        self.backtester.set_base_config(_base_cfg)
        
        # 添加数据源配置（支持单数据源和多数据源）
        if 'data_sources' in self.config:
            # 多数据源模式：需要将同一品种的多个周期合并
            symbol_periods_map = {}  # {symbol: [period_config_list]}
            symbol_config_map = {}   # {symbol: config}
            
            # 导入合约参数获取函数和品种代码提取函数
            from ..data.contract_info import get_trading_params
            import re
            
            def extract_variety_code(symbol: str) -> str:
                """从合约代码中提取品种代码，如 rb888 -> rb, au2602 -> au"""
                match = re.match(r'^([a-zA-Z]+)', symbol)
                return match.group(1).lower() if match else symbol.lower()
            
            # 缓存同一品种的参数（用于跨期套利等场景，确保同品种使用相同手续费）
            variety_params_cache = {}  # {variety_code: auto_params}
            
            # 第一步：收集所有品种的周期配置
            for ds_config in self.config['data_sources']:
                symbol = ds_config['symbol']
                kline_period = ds_config.get('kline_period', '1d')
                adjust_type = ds_config.get('adjust_type', self.config.get('adjust_type', '1'))
                
                # 将周期配置添加到对应品种的列表中
                if symbol not in symbol_periods_map:
                    symbol_periods_map[symbol] = []
                    
                    # 自动获取合约参数（如果用户未手动指定）
                    auto_params = {}
                    variety_code = extract_variety_code(symbol)
                    
                    if 'contract_multiplier' not in ds_config or 'commission' not in ds_config:
                        # 优先使用已缓存的同品种参数（确保跨期套利等场景下同品种手续费一致）
                        if variety_code in variety_params_cache:
                            auto_params = variety_params_cache[variety_code]
                            # 打印复用参数信息
                            comm_per_lot = auto_params.get('commission_per_lot', 0)
                            if comm_per_lot > 0:
                                comm_info = f"手续费={comm_per_lot}元/手"
                            else:
                                comm_info = f"手续费率={auto_params.get('commission', 0)}"
                            print(f"[自动参数] {symbol}({auto_params.get('variety_name', '')}) -> "
                                  f"复用{variety_code}参数: {comm_info}")
                        else:
                            # 首次遇到该品种，从 API 获取参数
                            contract_params = get_trading_params(symbol)
                            if contract_params:
                                auto_params = contract_params
                                # 缓存该品种的参数
                                variety_params_cache[variety_code] = contract_params
                                # 打印自动获取的参数
                                comm_per_lot = contract_params.get('commission_per_lot', 0)
                                if comm_per_lot > 0:
                                    comm_info = f"手续费={comm_per_lot}元/手"
                                else:
                                    comm_info = f"手续费率={contract_params.get('commission', 0)}"
                                print(f"[自动参数] {symbol}({contract_params.get('variety_name', '')}) -> "
                                      f"contract_multiplier={contract_params.get('contract_multiplier')}, "
                                      f"price_tick={contract_params.get('price_tick')}, "
                                      f"margin_rate={contract_params.get('margin_rate')}, {comm_info}")
                    
                    # 保存品种的基础配置（优先使用用户指定 > 自动获取 > 默认值）
                    symbol_config_map[symbol] = {
                        'start_date': self.config.get('start_date'),
                        'end_date': self.config.get('end_date'),
                        # 新增: 精确时间范围和BAR线数量请求
                        'start_time': self.config.get('start_time'),
                        'end_time': self.config.get('end_time'),
                        'limit': self.config.get('limit'),
                        'initial_capital': _resolved_symbol_capitals.get(symbol, ds_config.get('initial_capital', top_level_capital)),
                        'commission': ds_config.get('commission',
                                                    auto_params.get('commission',
                                                    self.config.get('commission', 0.0001))),
                        'margin_rate': ds_config.get('margin_rate',
                                                     auto_params.get('margin_rate',
                                                     self.config.get('margin_rate', 0.1))),
                        'contract_multiplier': ds_config.get('contract_multiplier',
                                                              auto_params.get('contract_multiplier',
                                                              self.config.get('contract_multiplier', 10))),
                        'slippage_ticks': ds_config.get('slippage_ticks', 
                                                         self.config.get('slippage_ticks', 1)),
                        'price_tick': ds_config.get('price_tick',
                                                     auto_params.get('price_tick',
                                                     self.config.get('price_tick', 1.0))),
                        # 固定金额手续费（元/手）
                        'commission_per_lot': ds_config.get('commission_per_lot',
                                                             auto_params.get('commission_per_lot',
                                                             self.config.get('commission_per_lot', 0))),
                        'commission_close_per_lot': ds_config.get('commission_close_per_lot',
                                                                   auto_params.get('commission_close_per_lot',
                                                                   self.config.get('commission_close_per_lot', 0))),
                        'commission_close_today_per_lot': ds_config.get('commission_close_today_per_lot',
                                                                         auto_params.get('commission_close_today_per_lot',
                                                                         self.config.get('commission_close_today_per_lot', 0))),
                    }
                
                # 添加周期配置
                symbol_periods_map[symbol].append({
                    'kline_period': kline_period,
                    'adjust_type': adjust_type
                })
            
            # 第二步：为每个品种添加完整的配置（包含所有周期）
            for symbol, periods in symbol_periods_map.items():
                config = symbol_config_map[symbol].copy()
                config['periods'] = periods
                self.backtester.add_symbol_config(symbol=symbol, config=config)
        else:
            # 单数据源模式
            symbol = self.config['symbol']
            self.backtester.add_symbol_config(
                symbol=symbol,
                config={
                    'start_date': self.config.get('start_date'),
                    'end_date': self.config.get('end_date'),
                    # 新增: 精确时间范围和BAR线数量请求
                    'start_time': self.config.get('start_time'),
                    'end_time': self.config.get('end_time'),
                    'limit': self.config.get('limit'),
                    'initial_capital': self.config.get('initial_capital', 100000),
                    'commission': self.config.get('commission', 0.0001),
                    'margin_rate': self.config.get('margin_rate', 0.1),
                    'contract_multiplier': self.config.get('contract_multiplier', 10),
                    'slippage_ticks': self.config.get('slippage_ticks', 1),
                    'price_tick': self.config.get('price_tick', 1.0),
                    # 固定金额手续费（元/手）
                    'commission_per_lot': self.config.get('commission_per_lot', 0),
                    'commission_close_per_lot': self.config.get('commission_close_per_lot', 0),
                    'commission_close_today_per_lot': self.config.get('commission_close_today_per_lot', 0),
                    'periods': [
                        {
                            'kline_period': self.config['kline_period'],
                            'adjust_type': self.config.get('adjust_type', '1')
                        }
                    ]
                }
            )
        
        # 将回测期实际生效的品种配置注入策略参数，便于策略按真实初始资金/乘数/保证金率计算仓位。
        effective_strategy_params = dict(self.strategy_params or {})
        effective_strategy_params['symbol_configs'] = {
            symbol: config.copy() for symbol, config in self.backtester.symbol_configs.items()
        }

        # 运行回测
        results = self.backtester.run(
            strategy=self.strategy_func,
            initialize=self.initialize_func,
            strategy_params=effective_strategy_params
        )
        
        return results
    
    def _run_simnow(self) -> Dict[str, Any]:
        """运行SIMNOW模拟交易"""
        from .live_trading_adapter import LiveTradingAdapter
        
        # 验证策略函数
        if not self.strategy_func:
            raise ValueError("策略函数不能为空")
        
        # 创建实盘适配器
        self.live_runner = LiveTradingAdapter(
            mode='simnow',
            config=self.config,
            strategy_func=self.strategy_func,
            initialize_func=self.initialize_func,
            strategy_params=self.strategy_params,
            on_trade_callback=self.on_trade_callback,
            on_order_callback=self.on_order_callback,
            on_cancel_callback=self.on_cancel_callback,
            on_order_error_callback=self.on_order_error_callback,
            on_cancel_error_callback=self.on_cancel_error_callback,
            on_account_callback=self.on_account_callback,
            on_position_callback=self.on_position_callback,
            on_position_complete_callback=self.on_position_complete_callback,
            on_disconnect_callback=self.on_disconnect_callback,
            on_query_trade_callback=self.on_query_trade_callback,
            on_query_trade_complete_callback=self.on_query_trade_complete_callback,
            on_query_order_callback=self.on_query_order_callback,
            on_query_order_complete_callback=self.on_query_order_complete_callback
        )
        
        # 运行
        results = self.live_runner.run()
        
        return results
    
    def _run_real_trading(self) -> Dict[str, Any]:
        """运行实盘交易"""
        from .live_trading_adapter import LiveTradingAdapter
        
        # 验证策略函数
        if not self.strategy_func:
            raise ValueError("策略函数不能为空")
        
        # 创建实盘适配器
        self.live_runner = LiveTradingAdapter(
            mode='real',
            config=self.config,
            strategy_func=self.strategy_func,
            initialize_func=self.initialize_func,
            strategy_params=self.strategy_params,
            on_trade_callback=self.on_trade_callback,
            on_order_callback=self.on_order_callback,
            on_cancel_callback=self.on_cancel_callback,
            on_order_error_callback=self.on_order_error_callback,
            on_cancel_error_callback=self.on_cancel_error_callback,
            on_account_callback=self.on_account_callback,
            on_position_callback=self.on_position_callback,
            on_position_complete_callback=self.on_position_complete_callback,
            on_disconnect_callback=self.on_disconnect_callback,
            on_query_trade_callback=self.on_query_trade_callback,
            on_query_trade_complete_callback=self.on_query_trade_complete_callback,
            on_query_order_callback=self.on_query_order_callback,
            on_query_order_complete_callback=self.on_query_order_complete_callback
        )
        
        # 运行
        results = self.live_runner.run()
        
        return results
    
    def stop(self):
        """停止运行"""
        if self.live_runner:
            self.live_runner.stop()
            print("[统一运行器] 已停止")
