import pandas as pd
from ..data.multi_data_fetcher import fetch_multiple_data
from ..data.data_source import MultiDataSource
from ..data.api_data_fetcher import get_futures_data
from ..data.local_data_loader import load_local_data
import os

class BacktestDataManager:
    """回测数据管理器，负责数据获取和处理相关功能"""
    
    def __init__(self, logger=None):
        """初始化数据管理器
        
        Args:
            logger: 日志管理器实例
        """
        self.logger = logger
        self.multi_data_source = MultiDataSource()
        self.data_dict = {}
    
    def log(self, message):
        """记录日志
        
        Args:
            message: 日志消息
        """
        if self.logger:
            self.logger.log_message(message)
        else:
            print(message)
    
    def fetch_data(self, symbols_and_periods, symbol_configs, base_config):
        """获取回测数据
        
        Args:
            symbols_and_periods: 品种和周期列表
            symbol_configs: 品种配置字典
            base_config: 基础配置
            
        Returns:
            multi_data_source: 多数据源实例
        """
        self.log("\n获取回测数据...")
        
        # 初始化数据字典
        data_dict = {}
        
        # 获取所有品种和周期的数据
        symbols = list(symbol_configs.keys())
        for symbol in symbols:
            config = symbol_configs[symbol]
            
            # 构建数据获取参数
            data_params = {
                'symbol': symbol,
                'start_date': config.get('start_date'),
                'end_date': config.get('end_date'),
                'username': base_config.get('username', ''),
                'password': base_config.get('password', ''),
                'use_cache': base_config.get('use_cache', True),
                'save_data': base_config.get('save_data', True)
            }
            
            # 获取该品种的所有周期数据
            for period_config in config.get('periods', []):
                kline_period = period_config.get('kline_period', '1h')
                adjust_type = period_config.get('adjust_type', '1')
                
                # 优先加载本地数据
                if 'file_path' in config and config['file_path']:
                    # 检查file_path是字符串还是列表
                    if isinstance(config['file_path'], list):
                        # 列表情况：检查至少有一个文件存在
                        files_exist = [os.path.exists(fp) for fp in config['file_path']]
                        if any(files_exist):
                            self.log(f"加载多个本地数据文件: {config['file_path']}")
                            try:
                                df = load_local_data(
                                    config['file_path'], 
                                    start_date=data_params['start_date'], 
                                    end_date=data_params['end_date']
                                )
                                key = f"{symbol}_{kline_period}_{adjust_type}"
                                data_dict[key] = df
                                self.log(f"多文件数据加载成功，共 {len(df)} 条K线数据")
                                continue  # 跳过API/数据库分支
                            except Exception as e:
                                self.log(f"多文件数据加载失败: {e}")
                                # 继续尝试API/数据库
                    # 单文件情况
                    elif os.path.exists(config['file_path']):
                        self.log(f"直接加载本地数据: {config['file_path']}")
                        try:
                            df = load_local_data(
                                config['file_path'], 
                                start_date=data_params['start_date'], 
                                end_date=data_params['end_date']
                            )
                            key = f"{symbol}_{kline_period}_{adjust_type}"
                            data_dict[key] = df
                            self.log(f"本地数据加载成功，共 {len(df)} 条K线数据")
                            continue  # 跳过API/数据库分支
                        except Exception as e:
                            self.log(f"本地数据加载失败: {e}")
                            # 继续尝试API/数据库
                
                # 原有API/数据库分支
                self.log(f"获取 {symbol} {kline_period} {'不复权' if adjust_type == '0' else '后复权'} 数据...")
                
                try:
                    # 详细记录参数
                    self.log(f"调用参数: symbol={symbol}, "
                                f"start_date={data_params['start_date']}, "
                                f"end_date={data_params['end_date']}, "
                                f"kline_period={kline_period}, "
                                f"adjust_type={adjust_type}, "
                                f"use_cache={data_params['use_cache']}")
                    
                    # 使用get_futures_data获取数据
                    klines = get_futures_data(
                        symbol=symbol,
                        start_date=data_params['start_date'],
                        end_date=data_params['end_date'],
                        username=data_params['username'],
                        password=data_params['password'],
                        kline_period=kline_period,
                        adjust_type=adjust_type,
                        depth="no",
                        use_cache=data_params['use_cache'],
                        save_data=data_params['save_data']
                    )
                    
                    if klines is not None and not klines.empty:
                        key = f"{symbol}_{kline_period}_{adjust_type}"
                        data_dict[key] = klines
                        self.log(f"获取到 {len(klines)} 条K线数据")
                    else:
                        self.log(f"警告：未获取到 {symbol} {kline_period} 数据，返回值为None或空DataFrame")
                except Exception as e:
                    self.log(f"获取数据出错：{str(e)}")
                    
                    # 尝试使用备选方法获取数据
                    self.log("尝试使用备选方法获取数据...")
                    try:
                        # 构建备选数据获取参数
                        alt_symbols_and_periods = [{
                            'symbol': symbol,
                            'kline_period': kline_period,
                            'adjust_type': adjust_type
                        }]
                        
                        # 构建品种配置字典
                        alt_configs = {
                            symbol: {
                                'start_date': data_params['start_date'],
                                'end_date': data_params['end_date'],
                                'username': data_params['username'],
                                'password': data_params['password'],
                                'use_cache': data_params['use_cache'],
                                'save_data': data_params['save_data']
                            }
                        }
                        
                        # 获取备选数据
                        alt_data_dict = fetch_multiple_data(alt_symbols_and_periods, alt_configs)
                        
                        key = f"{symbol}_{kline_period}_{adjust_type}"
                        if key in alt_data_dict and alt_data_dict[key] is not None and not alt_data_dict[key].empty:
                            data_dict[key] = alt_data_dict[key]
                            self.log(f"使用备选方法获取到 {len(alt_data_dict[key])} 条K线数据")
                        else:
                            self.log("使用备选方法也未能获取数据")
                    except Exception as e2:
                        self.log(f"备选方法也失败：{str(e2)}")
        
        self.data_dict = data_dict
        return data_dict
    
    def create_data_sources(self, symbols_and_periods, data_dict, lookback_bars: int = 0):
        """创建多数据源
        
        Args:
            symbols_and_periods: 品种和周期列表
            data_dict: 数据字典
            lookback_bars: K线回溯窗口大小，0表示不限制（返回全部历史数据）
            
        Returns:
            multi_data_source: 多数据源实例
        """
        # 创建多数据源
        for i, item in enumerate(symbols_and_periods):
            symbol = item['symbol']
            kline_period = item['kline_period']
            adjust_type = item['adjust_type']
            
            # 获取数据
            key = f"{symbol}_{kline_period}_{adjust_type}"
            if key in data_dict:
                data = data_dict[key]
                # 添加数据源（传入lookback_bars参数）
                self.multi_data_source.add_data_source(symbol, kline_period, adjust_type, data, 
                                                       lookback_bars=lookback_bars)
                self.log(f"添加数据源 #{i}: {symbol} {kline_period} adjust_type={adjust_type} lookback={lookback_bars}")
            else:
                # 如果没有获取到这个周期的数据，添加一个空数据源
                self.log(f"警告：未找到 {symbol} {kline_period} adjust_type={adjust_type} 数据，添加空数据源")
                self.multi_data_source.add_data_source(symbol, kline_period, adjust_type, 
                                                       lookback_bars=lookback_bars)
        
        return self.multi_data_source
    
    def align_data(self, align=True, fill_method='ffill'):
        """对齐多数据源的数据
        
        Args:
            align: 是否对齐数据
            fill_method: 填充方法，默认为'ffill'
            
        Returns:
            multi_data_source: 多数据源实例
        """
        if align and len(self.multi_data_source) > 1:
            self.log("对齐数据...")
            self.multi_data_source.align_data(
                align_index=True, 
                fill_method=fill_method
            )
        
        return self.multi_data_source
    
    def get_data_source(self):
        """获取多数据源实例
        
        Returns:
            multi_data_source: 多数据源实例
        """
        return self.multi_data_source 