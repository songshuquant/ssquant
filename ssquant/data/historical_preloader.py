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
                history_symbol: str = None,
                kline_source: str = 'data_server') -> pd.DataFrame:
        """
        预加载历史数据（按K线数量加载）
        
        Args:
            specific_contract: 具体合约代码，如 rb2601
            period: K线周期，如 1M, 1H, 1D
            lookback_bars: 回看K线数量，默认100根
            adjust_type: 复权类型，'0'不复权 '1'后复权 '2'前复权
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
        
        # 本地复权开关
        try:
            from ..config.trading_config import ENABLE_REMOTE_ADJUST
        except ImportError:
            ENABLE_REMOTE_ADJUST = True
        
        if not ENABLE_REMOTE_ADJUST and adjust_type != '0':
            print(f"[预加载] 本地复权已禁用，adjust_type 已从 '{adjust_type}' 强制改为 '0'")
            adjust_type = '0'
        
        # 2. 构建表名（周期统一用大写，如 1M, 5M）
        # TICK数据没有复权概念，表名直接是 {symbol}_tick
        if period.lower() == 'tick':
            table_name = f"{continuous_symbol}_tick"
        else:
            from .local_adjust import get_adjust_label, get_adjust_suffix
            table_suffix = get_adjust_suffix(adjust_type)
            # 周期转大写，与云端数据保存格式一致
            period_upper = period.upper()
            table_name = f"{continuous_symbol}_{period_upper}_{table_suffix}"
        
        print(f"\n{'='*60}")
        print(f"【历史数据预加载】")
        print(f"{'='*60}")
        print(f"具体合约: {specific_contract}")
        print(f"主连符号: {continuous_symbol}")
        from .local_adjust import get_adjust_label
        print(f"复权类型: {adjust_type} ({get_adjust_label(adjust_type)})")
        print(f"表名: {table_name}")
        print(f"加载K线数: {lookback_bars} 根")
        
        # 3. K线数据预加载
        #    TICK 数据仍走本地数据库（data_server 不提供 TICK）
        if period.lower() != 'tick':
            # local 模式：直接从本地数据库读取，不走 data_server
            if kline_source == 'local':
                print(f"→ 【本地K线模式】跳过 data_server，直接从本地数据库读取...")
                df = self._fallback_local_db(continuous_symbol, period, lookback_bars,
                                             adjust_type, table_name)
                if not df.empty:
                    print(f"{'='*60}\n")
                    return df
                print(f"❌ 本地数据库无数据: {continuous_symbol} {period}")
                print(f"  请先用 examples/A_工具_导入数据库DB示例.py 导入本地数据")
                print(f"  支持格式: CSV / Excel / JSON / Parquet / Feather / Pickle")
                print(f"{'='*60}\n")
                return pd.DataFrame()
            
            # data_server 模式（默认）：从远程获取，失败后备本地
            print(f"→ 从 data_server 获取 {period.upper()} 数据...")
            df = self._fetch_from_data_server(continuous_symbol, period, lookback_bars, adjust_type)
            if not df.empty:
                print(f"✅ 预加载完成: {len(df)} 条 {period.upper()} K线")
                print(f"数据范围: {df.index[0]} 至 {df.index[-1]}")
                print(f"{'='*60}\n")
                return df
            
            # data_server 不可用时，回退到本地数据库
            print(f"⚠️ data_server 获取失败，尝试本地数据库回退...")
            df = self._fallback_local_db(continuous_symbol, period, lookback_bars,
                                         adjust_type, table_name)
            if not df.empty:
                print(f"{'='*60}\n")
                return df
            
            print(f"❌ 无法获取数据: {continuous_symbol} {period}")
            print(f"{'='*60}\n")
            return pd.DataFrame()
        
        # 4. TICK 数据：从本地数据库读取（data_server 不提供 TICK）
        if not os.path.exists(self.db_path):
            print(f"⚠️ 本地数据库不存在: {self.db_path}")
            print(f"{'='*60}\n")
            return pd.DataFrame()
        
        try:
            conn = sqlite3.connect(self.db_path, timeout=30)
            cursor = conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            
            cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}'")
            if cursor.fetchone() is None:
                print(f"⚠️ TICK表不存在: {table_name}")
                conn.close()
                print(f"{'='*60}\n")
                return pd.DataFrame()
            
            query = f"""
                SELECT * FROM (
                    SELECT * FROM "{table_name}"
                    ORDER BY datetime DESC
                    LIMIT ?
                ) sub
                ORDER BY datetime ASC
            """
            df = pd.read_sql_query(query, conn, params=(lookback_bars,))
            conn.close()
            
            if not df.empty:
                df['datetime'] = pd.to_datetime(df['datetime'], format='mixed')
                df = df.set_index('datetime')
                print(f"✅ 本地加载 {len(df)} 条TICK数据")
                print(f"数据范围: {df.index[0]} 至 {df.index[-1]}")
            else:
                print(f"⚠️ TICK表无数据: {table_name}")
            
            print(f"{'='*60}\n")
            return df
            
        except Exception as e:
            print(f"❌ 预加载TICK失败: {e}")
            print(f"{'='*60}\n")
            import traceback
            traceback.print_exc()
            return pd.DataFrame()
    
    def _fallback_local_db(self, continuous_symbol: str, period: str,
                           lookback_bars: int, adjust_type: str,
                           table_name: str) -> pd.DataFrame:
        """
        data_server 不可用时，回退到本地数据库。
        优先从 1M 表聚合，其次尝试目标周期表。
        """
        if not os.path.exists(self.db_path):
            print(f"→ 本地数据库不存在: {self.db_path}")
            return pd.DataFrame()
        
        try:
            from .local_adjust import apply_local_adjust, get_adjust_suffix
            table_suffix = get_adjust_suffix(adjust_type)
            need_local_adjust = adjust_type != '0'
            conn = sqlite3.connect(self.db_path, timeout=30)
            cursor = conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            
            # 非 1M 周期：优先从 1M 表聚合
            is_non_1m = period.lower() not in ('1m', '1min', 'tick')
            if is_non_1m:
                df = self._try_load_from_1m(cursor, conn, continuous_symbol,
                                            period, lookback_bars, table_suffix)
                used_raw_1m_fallback = False
                if (df is None or df.empty) and need_local_adjust and table_suffix != 'raw':
                    df = self._try_load_from_1m(cursor, conn, continuous_symbol,
                                                period, lookback_bars, 'raw')
                    used_raw_1m_fallback = df is not None and not df.empty
                if df is not None and not df.empty:
                    if used_raw_1m_fallback:
                        df = apply_local_adjust(df, continuous_symbol, period, adjust_type)
                    conn.close()
                    print(f"✅ 本地回退: 1M→{period.upper()} 聚合 {len(df)} 条")
                    print(f"数据范围: {df.index[0]} 至 {df.index[-1]}")
                    return df
            
            # 尝试目标周期表
            possible_names = [
                table_name,
                f"{continuous_symbol}_{period.lower()}_{table_suffix}",
                f"{continuous_symbol}_{period.upper()}_{table_suffix}",
            ]
            if need_local_adjust and table_suffix != 'raw':
                possible_names.extend([
                    f"{continuous_symbol}_{period.lower()}_raw",
                    f"{continuous_symbol}_{period.upper()}_raw",
                ])
            actual_table = None
            for name in possible_names:
                cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{name}'")
                if cursor.fetchone() is not None:
                    actual_table = name
                    break
            
            if actual_table is None:
                conn.close()
                print(f"→ 本地无可用表")
                return pd.DataFrame()
            
            query = f"""
                SELECT * FROM (
                    SELECT * FROM "{actual_table}"
                    ORDER BY datetime DESC
                    LIMIT ?
                ) sub
                ORDER BY datetime ASC
            """
            df = pd.read_sql_query(query, conn, params=(lookback_bars,))
            conn.close()
            
            if not df.empty:
                df['datetime'] = pd.to_datetime(df['datetime'])
                df = df.set_index('datetime')
                if need_local_adjust and actual_table.lower().endswith('_raw'):
                    df = apply_local_adjust(df, continuous_symbol, period, adjust_type)
                print(f"✅ 本地回退: 从 {actual_table} 加载 {len(df)} 条")
                print(f"数据范围: {df.index[0]} 至 {df.index[-1]}")
            
            return df
            
        except Exception as e:
            print(f"→ 本地回退失败: {e}")
            return pd.DataFrame()

    @staticmethod
    def _estimate_1m_bars(target_period: str, target_bars: int) -> int:
        """
        估算需要多少根 1M K线才能聚合出 target_bars 根目标周期K线。
        加 20% 安全余量以应对夜盘/休市间隔。
        """
        import re as _re
        p = target_period.strip().lower()
        
        m = _re.match(r'^(\d+)(m|min)$', p)
        if m:
            ratio = int(m.group(1))
            return int(target_bars * ratio * 1.2) + 50
        
        m = _re.match(r'^(\d+)(h|hour)$', p)
        if m:
            ratio = int(m.group(1)) * 60
            return int(target_bars * ratio * 1.2) + 50
        
        if p in ('1d', 'd', 'day'):
            # 期货一天约 240~300 根 1M（含夜盘）
            return int(target_bars * 300 * 1.2) + 50
        
        # 未知周期，给大一点
        return target_bars * 60

    def _try_load_from_1m(self, cursor, conn, continuous_symbol: str,
                          target_period: str, lookback_bars: int,
                          table_suffix: str):
        """
        尝试从本地 1M 表读取数据并聚合为目标周期。
        
        Returns:
            聚合后的 DataFrame（datetime 索引），如果 1M 表不存在则返回 None。
        """
        # 查找 1M 表
        possible_1m_names = [
            f"{continuous_symbol}_1M_{table_suffix}",
            f"{continuous_symbol}_1m_{table_suffix}",
        ]
        
        actual_1m_table = None
        for name in possible_1m_names:
            cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{name}'")
            if cursor.fetchone() is not None:
                actual_1m_table = name
                break
        
        if actual_1m_table is None:
            print(f"→ 本地 1M 表不存在，无法本地聚合")
            return None
        
        # 估算需要多少根 1M 数据
        need_1m_bars = self._estimate_1m_bars(target_period, lookback_bars)
        
        print(f"→ 从本地 1M 表聚合: 读取 ~{need_1m_bars} 根 1M → {target_period.upper()}")
        
        query = f"""
            SELECT * FROM (
                SELECT * FROM "{actual_1m_table}"
                ORDER BY datetime DESC
                LIMIT ?
            ) sub
            ORDER BY datetime ASC
        """
        
        df_1m = pd.read_sql_query(query, conn, params=(need_1m_bars,))
        
        if df_1m.empty:
            return None
        
        df_1m['datetime'] = pd.to_datetime(df_1m['datetime'])
        df_1m = df_1m.set_index('datetime')
        
        # 本地聚合
        from .multi_period import aggregate_1m_to_period
        df_agg = aggregate_1m_to_period(df_1m, target_period)
        
        if df_agg is None or df_agg.empty:
            return None
        
        # 截取最近 lookback_bars 根
        if len(df_agg) > lookback_bars:
            df_agg = df_agg.iloc[-lookback_bars:]
        
        return df_agg
    
    def _fetch_from_data_server(self, symbol: str, period: str,
                                lookback_bars: int, adjust_type: str) -> pd.DataFrame:
        """Preload via the same authenticated SDK client as remote history and WS."""
        from .sdk_client import history_frame

        frame = history_frame(symbol, period, limit=lookback_bars, preload=True)
        if not frame.empty and str(adjust_type) != '0':
            from .local_adjust import apply_local_adjust
            frame = apply_local_adjust(frame, symbol, period, adjust_type)
        return frame

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
                for suffix in ['raw', 'hfq', 'qfq']:
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

