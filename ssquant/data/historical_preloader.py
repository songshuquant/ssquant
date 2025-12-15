"""
历史数据预加载器
用于实盘/SIMNOW模式启动时预加载历史数据
"""

import pandas as pd
import sqlite3
import os


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
        
        # 2. 构建表名
        # TICK数据没有复权概念，表名直接是 {symbol}_tick
        if period.lower() == 'tick':
            table_name = f"{continuous_symbol}_tick"
        else:
            table_suffix = 'hfq' if adjust_type == '1' else 'raw'
            table_name = f"{continuous_symbol}_{period}_{table_suffix}"
        
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
            print(f"❌ 数据库不存在: {self.db_path}")
            print(f"返回空数据")
            print(f"{'='*60}\n")
            return pd.DataFrame()
        
        # 4. 从数据库读取最近N根K线
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # 检查表是否存在
            cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}'")
            table_exists = cursor.fetchone() is not None
            
            if not table_exists:
                print(f"❌ 表不存在: {table_name}")
                print(f"提示：请确保 adjust_type 参数与回测时保持一致")
                print(f"     - 回测使用后复权 → 实盘也需设置 adjust_type='1'")
                print(f"     - 回测使用不复权 → 实盘也需设置 adjust_type='0'")
                print(f"返回空数据")
                print(f"{'='*60}\n")
                conn.close()
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
                
                print(f"✅ 成功加载 {len(df)} 条历史数据")
                print(f"数据范围: {df.index[0]} 至 {df.index[-1]}")
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
    
    def preload_tick(self, specific_contract: str, 
                     lookback_count: int = 1000,
                     history_symbol: str = None) -> pd.DataFrame:
        """
        预加载历史TICK数据（专门用于TICK数据预加载）
        
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
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
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
                # 转换datetime列
                df['datetime'] = pd.to_datetime(df['datetime'])
                
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
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # 检查表
            # TICK数据没有复权概念，表名直接是 {symbol}_tick
            if period.lower() == 'tick':
                tables_to_check = [f"{continuous_symbol}_tick"]
            else:
                tables_to_check = [f"{continuous_symbol}_{period}_{suffix}" for suffix in ['raw', 'hfq']]
            
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

