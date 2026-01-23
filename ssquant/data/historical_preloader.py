"""
历史数据预加载器
用于实盘/SIMNOW模式启动时预加载历史数据
支持本地缓存优先，本地不存在时自动从云服务器获取
"""

import pandas as pd
import sqlite3
import os
from datetime import datetime, timedelta


class HistoricalDataPreloader:
    """实盘/SIMNOW模式的历史数据预加载器"""
    
    def __init__(self, db_path: str = "data_cache/backtest_data.db"):
        """
        初始化预加载器
        
        Args:
            db_path: 数据库路径
        """
        self.db_path = db_path
    
    def preload(self, specific_contract: str, period: str, 
                lookback_bars: int = 100, adjust_type: str = '0',
                history_symbol: str = None) -> pd.DataFrame:
        """
        预加载历史数据（按K线数量加载）
        
        Args:
            specific_contract: 具体合约代码，如 rb2601
            period: K线周期，如 1M, 1H, 1D
            lookback_bars: 回看K线数量，默认100根
            adjust_type: 复权类型，'0'不复权 '1'后复权
            history_symbol: 自定义历史数据符号，如 'rb888' 或 'rb777'
                          如果不指定，则自动推导为主力连续（XXX888）
            
        Returns:
            历史K线DataFrame（带datetime索引）
        """
        from ..data.contract_mapper import ContractMapper
        
        # 1. 确定数据源符号
        if history_symbol:
            # 用户指定了历史数据符号（如 rb777 次主力）
            continuous_symbol = history_symbol.lower()
        else:
            # 默认推导为主力连续（XXX888）
            continuous_symbol = ContractMapper.get_continuous_symbol(specific_contract)
        
        # 检查远程后复权开关，保持与 api_data_fetcher.py 一致
        try:
            from ..config.trading_config import ENABLE_REMOTE_ADJUST
        except ImportError:
            ENABLE_REMOTE_ADJUST = False
        
        if not ENABLE_REMOTE_ADJUST and adjust_type == '1':
            print(f"[预加载] 远程服务器升级中暂不支持后复权，adjust_type 已从 '1' 强制改为 '0'")
            adjust_type = '0'
        
        # 2. 构建表名（周期统一用大写，如 1M, 5M）
        # TICK数据没有复权概念，表名直接是 {symbol}_tick
        if period.lower() == 'tick':
            table_name = f"{continuous_symbol}_tick"
        else:
            table_suffix = 'hfq' if adjust_type == '1' else 'raw'
            # 周期转大写，与云端数据保存格式一致
            period_upper = period.upper()
            table_name = f"{continuous_symbol}_{period_upper}_{table_suffix}"
        
        print(f"\n{'='*60}")
        print(f"【历史数据预加载】")
        print(f"{'='*60}")
        print(f"具体合约: {specific_contract}")
        print(f"主连符号: {continuous_symbol}")
        print(f"复权类型: {adjust_type} ({'后复权' if adjust_type == '1' else '不复权'})")
        print(f"表名: {table_name}")
        print(f"加载K线数: {lookback_bars} 根")
        
        # 3. 检查数据库是否存在
        if not os.path.exists(self.db_path):
            print(f"⚠️ 本地数据库不存在: {self.db_path}")
            
            # 检查是否启用云端数据
            if self._is_cloud_enabled():
                print(f"→ 尝试从云服务器获取数据...")
                
                # 尝试从云服务器获取数据
                df = self._fetch_from_cloud(continuous_symbol, period, lookback_bars, adjust_type)
                if not df.empty:
                    print(f"✅ 云端获取成功，已缓存到本地")
                    print(f"{'='*60}\n")
                    return df
                else:
                    print(f"❌ 云端也没有数据: {continuous_symbol}")
                    print(f"{'='*60}\n")
                    return pd.DataFrame()
            else:
                print(f"⚠️ 云端数据已关闭 (ENABLE_CLOUD_DATA=False)")
                print(f"{'='*60}\n")
                return pd.DataFrame()
        
        # 4. 从数据库读取最近N根K线
        try:
            conn = sqlite3.connect(self.db_path, timeout=30)
            cursor = conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")  # WAL模式：支持并发读写
            
            # 检查表是否存在（兼容大小写）
            # 尝试原始表名、小写周期、大写周期
            possible_names = [
                table_name,  # 原始表名
                f"{continuous_symbol}_{period.lower()}_{table_suffix}",  # 小写周期
                f"{continuous_symbol}_{period.upper()}_{table_suffix}",  # 大写周期
            ]
            
            actual_table_name = None
            for name in possible_names:
                cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{name}'")
                if cursor.fetchone() is not None:
                    actual_table_name = name
                    break
            
            table_exists = actual_table_name is not None
            if table_exists:
                table_name = actual_table_name  # 使用实际存在的表名
            
            if not table_exists:
                print(f"⚠️ 本地表不存在: {table_name}")
                conn.close()
                
                # 检查是否启用云端数据
                if self._is_cloud_enabled():
                    print(f"→ 尝试从云服务器获取数据...")
                    
                    # 尝试从云服务器获取数据
                    df = self._fetch_from_cloud(continuous_symbol, period, lookback_bars, adjust_type)
                    if not df.empty:
                        print(f"✅ 云端获取成功，已缓存到本地")
                        print(f"{'='*60}\n")
                        return df
                    else:
                        print(f"❌ 云端也没有数据: {continuous_symbol}")
                        print(f"{'='*60}\n")
                        return pd.DataFrame()
                else:
                    print(f"⚠️ 云端数据已关闭 (ENABLE_CLOUD_DATA=False)")
                    print(f"{'='*60}\n")
                    return pd.DataFrame()
            
            # 读取最近N根K线（先按时间倒序取N条，然后再正序排列）
            query = f"""
                SELECT * FROM (
                    SELECT * FROM {table_name}
                    ORDER BY datetime DESC
                    LIMIT ?
                ) sub
                ORDER BY datetime ASC
            """
            
            df = pd.read_sql_query(
                query, 
                conn, 
                params=(lookback_bars,)
            )
            
            conn.close()
            
            if not df.empty:
                # 转换datetime列
                df['datetime'] = pd.to_datetime(df['datetime'])
                
                # 设置索引
                df = df.set_index('datetime')
                
                print(f"✅ 本地加载 {len(df)} 条历史数据")
                print(f"数据范围: {df.index[0]} 至 {df.index[-1]}")
                
                # 检查数据是否过期（最新数据不是今天）
                latest_date = df.index[-1].date()
                today = datetime.now().date()
                
                if latest_date < today and self._is_cloud_enabled():
                    print(f"⚠️ 本地数据已过期（最新: {latest_date}，今天: {today}）")
                    print(f"→ 尝试从云端获取最新数据...")
                    
                    # 从云端获取更新的数据
                    cloud_df = self._fetch_from_cloud(continuous_symbol, period, lookback_bars, adjust_type)
                    
                    if not cloud_df.empty:
                        cloud_latest = cloud_df.index[-1].date()
                        if cloud_latest > latest_date:
                            print(f"✅ 云端数据更新（最新: {cloud_latest}）")
                            print(f"{'='*60}\n")
                            return cloud_df
                        else:
                            print(f"→ 云端数据无更新，使用本地数据")
                    else:
                        print(f"→ 云端获取失败，使用本地数据")
                
            else:
                print(f"⚠️  表 {table_name} 存在但无数据")
                print(f"可能原因：请求的日期范围内没有数据")
            
            print(f"{'='*60}\n")
            return df
            
        except Exception as e:
            print(f"❌ 预加载失败: {e}")
            print(f"{'='*60}\n")
            import traceback
            traceback.print_exc()
            return pd.DataFrame()
    
    def _is_cloud_enabled(self) -> bool:
        """检查是否启用云端数据获取"""
        try:
            from ..config.trading_config import ENABLE_CLOUD_DATA
            return ENABLE_CLOUD_DATA
        except ImportError:
            # 如果配置不存在，默认启用
            return True
    
    def _fetch_from_cloud(self, symbol: str, period: str, 
                          lookback_bars: int, adjust_type: str) -> pd.DataFrame:
        """
        从云服务器获取数据并缓存到本地
        
        Args:
            symbol: 连续合约符号，如 tl888
            period: K线周期，如 1m, 5m
            lookback_bars: 需要的K线数量
            adjust_type: 复权类型
            
        Returns:
            历史K线DataFrame
        """
        try:
            # 获取API凭据
            from ..config.trading_config import get_api_auth
            username, password = get_api_auth()
            
            if not username or not password:
                print(f"⚠️ 未配置API账号，请在 ssquant/config/trading_config.py 中设置")
                return pd.DataFrame()
            
            # 计算日期范围（往前推足够天数以获取足够K线）
            end_date = datetime.now().strftime('%Y-%m-%d')
            
            # 根据周期估算需要的天数
            period_lower = period.lower()
            if period_lower in ['1m', '1M']:
                # 1分钟K线，一天约240根，100根约0.5天，多取30天
                days_back = max(30, lookback_bars // 240 + 10)
            elif period_lower in ['5m', '5M']:
                # 5分钟K线，一天约48根，100根约2天，多取30天
                days_back = max(30, lookback_bars // 48 + 10)
            elif period_lower in ['15m', '15M']:
                # 15分钟K线，一天约16根，100根约7天，多取30天
                days_back = max(30, lookback_bars // 16 + 10)
            elif period_lower in ['30m', '30M']:
                days_back = max(30, lookback_bars // 8 + 10)
            elif period_lower in ['1h', '60m', '1H', '60M']:
                days_back = max(60, lookback_bars // 4 + 10)
            elif period_lower in ['1d', '1D', 'd', 'D']:
                days_back = max(365, lookback_bars + 30)
            else:
                days_back = 60  # 默认60天
            
            start_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d')
            
            # 转换周期格式（ssquant API 使用 1M, 5M 等格式）
            period_map = {
                '1m': '1M', '5m': '5M', '15m': '15M', '30m': '30M',
                '1h': '1H', '60m': '1H', '1d': '1D', 'd': '1D'
            }
            api_period = period_map.get(period_lower, period.upper())
            
            print(f"→ 请求云端数据: {symbol} {api_period} ({start_date} ~ {end_date})")
            
            # 调用API获取数据
            from .api_data_fetcher import get_futures_data
            
            data = get_futures_data(
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
                username=username,
                password=password,
                kline_period=api_period,
                adjust_type=adjust_type,
                use_cache=True,  # 自动缓存到本地
                save_data=True
            )
            
            if data is None or data.empty:
                return pd.DataFrame()
            
            # 统一datetime字段并排序，避免范围显示与实际返回不一致
            if not isinstance(data.index, pd.DatetimeIndex):
                if 'datetime' in data.columns:
                    data['datetime'] = pd.to_datetime(data['datetime'])
                    data = data.sort_values('datetime')
                else:
                    return pd.DataFrame()
            else:
                data = data.sort_index()

            # 打印云端数据的实际范围（调试用）
            if isinstance(data.index, pd.DatetimeIndex):
                print(f"→ 云端数据实际范围: {data.index.min()} 至 {data.index.max()} (共 {len(data)} 条)")
            else:
                temp_dt = pd.to_datetime(data['datetime'])
                print(f"→ 云端数据实际范围: {temp_dt.min()} 至 {temp_dt.max()} (共 {len(data)} 条)")
            
            # 取最近N根K线
            if len(data) > lookback_bars:
                data = data.tail(lookback_bars)
            
            # 确保索引是datetime类型
            if not isinstance(data.index, pd.DatetimeIndex):
                data['datetime'] = pd.to_datetime(data['datetime'])
                data = data.set_index('datetime')
            
            return data
            
        except Exception as e:
            print(f"❌ 云端获取失败: {e}")
            import traceback
            traceback.print_exc()
            return pd.DataFrame()
    
    def preload_tick(self, specific_contract: str, 
                     lookback_count: int = 1000,
                     history_symbol: str = None) -> pd.DataFrame:
        """
        预加载历史TICK数据（专门用于TICK数据预加载）
        
        注意: TICK数据只从本地数据库读取，不会从远程服务器获取（远程服务器没有TICK数据）
        
        Args:
            specific_contract: 具体合约代码，如 au2602
            lookback_count: 回看TICK数量，默认1000条
            history_symbol: 自定义历史数据符号
                          - 如果不指定，默认使用主连符号（如 au888）
                          - 可指定具体合约（如 au2602）或其他主连（如 au777）
            
        Returns:
            历史TICK数据DataFrame（带datetime索引）
        """
        from ..data.contract_mapper import ContractMapper
        
        # 1. 确定数据源符号
        # TICK数据默认使用主连符号存储（如 au888_tick），与保存逻辑一致
        if history_symbol:
            source_symbol = history_symbol.lower()
        else:
            # 默认推导为主力连续（XXX888），与数据保存时的逻辑一致
            source_symbol = ContractMapper.get_continuous_symbol(specific_contract)
        
        # 2. 构建表名
        table_name = f"{source_symbol}_tick"
        
        print(f"\n{'='*60}")
        print(f"【历史TICK数据预加载】")
        print(f"{'='*60}")
        print(f"合约代码: {specific_contract}")
        print(f"数据源符号: {source_symbol}")
        print(f"表名: {table_name}")
        print(f"加载TICK数: {lookback_count} 条")
        
        # 3. 检查数据库是否存在
        if not os.path.exists(self.db_path):
            print(f"❌ 数据库不存在: {self.db_path}")
            print(f"提示: 请先通过SIMNOW模式采集TICK数据（开启 save_tick_db=True）")
            print(f"返回空数据")
            print(f"{'='*60}\n")
            return pd.DataFrame()
        
        # 4. 从数据库读取最近N条TICK
        try:
            conn = sqlite3.connect(self.db_path, timeout=30)
            cursor = conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")  # WAL模式：支持并发读写
            
            # 检查表是否存在
            cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}'")
            table_exists = cursor.fetchone() is not None
            
            if not table_exists:
                print(f"❌ 表不存在: {table_name}")
                # 列出可用的tick表
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%_tick'")
                available = [row[0] for row in cursor.fetchall()]
                if available:
                    print(f"可用的TICK表: {available}")
                else:
                    print("数据库中没有TICK表，请先采集TICK数据")
                print(f"返回空数据")
                print(f"{'='*60}\n")
                conn.close()
                return pd.DataFrame()
            
            # 读取最近N条TICK（先按时间倒序取N条，然后再正序排列）
            query = f"""
                SELECT * FROM (
                    SELECT * FROM {table_name}
                    ORDER BY datetime DESC
                    LIMIT ?
                ) sub
                ORDER BY datetime ASC
            """
            
            df = pd.read_sql_query(
                query, 
                conn, 
                params=(lookback_count,)
            )
            
            conn.close()
            
            if not df.empty:
                # 转换datetime列（使用 mixed 格式支持有/无毫秒的混合数据）
                df['datetime'] = pd.to_datetime(df['datetime'], format='mixed')
                
                # 设置索引
                df = df.set_index('datetime')
                
                print(f"✅ 成功加载 {len(df)} 条历史TICK数据")
                print(f"数据范围: {df.index[0]} 至 {df.index[-1]}")
            else:
                print(f"⚠️  表 {table_name} 存在但无数据")
            
            print(f"{'='*60}\n")
            return df
            
        except Exception as e:
            print(f"❌ 预加载TICK失败: {e}")
            print(f"{'='*60}\n")
            import traceback
            traceback.print_exc()
            return pd.DataFrame()
    
    def check_available_data(self, specific_contract: str, period: str) -> dict:
        """
        检查可用的历史数据信息
        
        Args:
            specific_contract: 具体合约代码
            period: K线周期
            
        Returns:
            包含数据信息的字典
        """
        from ..data.contract_mapper import ContractMapper
        
        continuous_symbol = ContractMapper.get_continuous_symbol(specific_contract)
        
        result = {
            'specific_contract': specific_contract,
            'continuous_symbol': continuous_symbol,
            'period': period,
            'db_exists': False,
            'table_exists': False,
            'data_count': 0,
            'date_range': None,
        }
        
        # 检查数据库
        if not os.path.exists(self.db_path):
            return result
        
        result['db_exists'] = True
        
        try:
            conn = sqlite3.connect(self.db_path, timeout=30)
            cursor = conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")  # WAL模式：支持并发读写
            
            # 检查表（兼容大小写）
            # TICK数据没有复权概念，表名直接是 {symbol}_tick
            if period.lower() == 'tick':
                tables_to_check = [f"{continuous_symbol}_tick"]
            else:
                # 同时检查大小写两种周期格式
                tables_to_check = []
                for suffix in ['raw', 'hfq']:
                    tables_to_check.append(f"{continuous_symbol}_{period.lower()}_{suffix}")
                    tables_to_check.append(f"{continuous_symbol}_{period.upper()}_{suffix}")
            
            for table_name in tables_to_check:
                cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}'")
                
                if cursor.fetchone():
                    result['table_exists'] = True
                    result['table_name'] = table_name
                    
                    # 获取数据统计
                    cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                    count = cursor.fetchone()[0]
                    result['data_count'] = count
                    
                    if count > 0:
                        # 获取日期范围
                        cursor.execute(f"SELECT MIN(datetime), MAX(datetime) FROM {table_name}")
                        min_date, max_date = cursor.fetchone()
                        result['date_range'] = (min_date, max_date)
                    
                    break  # 找到第一个存在的表就停止
            
            conn.close()
            
        except Exception as e:
            print(f"检查数据出错: {e}")
        
        return result


if __name__ == '__main__':
    # 测试代码
    preloader = HistoricalDataPreloader()
    
    # 测试1: 检查可用数据
    print("\n【测试1: 检查可用数据】")
    info = preloader.check_available_data('rb2601', '1H')
    print(f"合约: {info['specific_contract']}")
    print(f"主连: {info['continuous_symbol']}")
    print(f"数据库存在: {info['db_exists']}")
    print(f"表存在: {info['table_exists']}")
    if info['table_exists']:
        print(f"表名: {info['table_name']}")
        print(f"数据条数: {info['data_count']}")
        if info['date_range']:
            print(f"日期范围: {info['date_range'][0]} 至 {info['date_range'][1]}")
    
    # 测试2: 预加载数据
    print("\n【测试2: 预加载数据】")
    df = preloader.preload('rb2601', '1H', lookback_bars=100)
    
    if not df.empty:
        print(f"\n预加载成功！")
        print(f"数据形状: {df.shape}")
        print(f"\n前5条数据:")
        print(df.head())

