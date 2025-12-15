import os
import pandas as pd


def load_local_data(file_path, start_date=None, end_date=None, **kwargs):
    """
    支持CSV、HDF5、7z格式的本地行情数据加载，并自动校验字段。
    K线数据必须字段: datetime, open, high, low, close
    Tick数据必须字段: datetime, price, volume
    推荐字段: volume, symbol
    
    参数:
        file_path: 可以是单个文件路径(字符串)或多个文件路径列表([字符串])，
                  当传入列表时，将按顺序加载并合并数据
        start_date: 开始日期，格式为"YYYY-MM-DD"，用于筛选数据
        end_date: 结束日期，格式为"YYYY-MM-DD"，用于筛选数据
    """
    # 处理file_path为列表的情况
    if isinstance(file_path, list):
        if not file_path:
            raise ValueError('文件路径列表为空')
        
        # 保存所有加载的数据框
        all_dfs = []
        
        # 逐个加载文件
        for single_file in file_path:
            if not os.path.exists(single_file):
                raise ValueError(f'文件不存在: {single_file}')
            
            # 递归调用单文件版本，但不传入日期筛选参数，等合并后再筛选
            df = load_local_data(single_file, **kwargs)
            all_dfs.append(df)
        
        # 合并所有数据框，按时间排序
        combined_df = pd.concat(all_dfs)
        combined_df = combined_df.sort_index()
        
        # 应用日期筛选
        if start_date is not None or end_date is not None:
            combined_df = filter_by_date_range(combined_df, start_date, end_date)
        
        return combined_df
    
    # 单文件处理逻辑
    if not os.path.exists(file_path):
        raise ValueError(f'文件不存在: {file_path}')
        
    ext = os.path.splitext(file_path)[-1].lower()
    if ext == '.csv':
        df = pd.read_csv(file_path, **kwargs)
    elif ext in ['.h5', '.hdf5']:
        key = kwargs.get('key', None)
        if key is None:
            raise ValueError('HDF5文件必须指定key参数')
        df = pd.read_hdf(file_path, key=key)
    elif ext == '.7z':
        import py7zr
        import tempfile
        with py7zr.SevenZipFile(file_path, mode='r') as z:
            tmpdir = tempfile.mkdtemp()
            z.extractall(path=tmpdir)
            for fname in os.listdir(tmpdir):
                if fname.endswith('.csv'):
                    df = pd.read_csv(os.path.join(tmpdir, fname))
                    break
            else:
                raise ValueError('7z压缩包中未找到CSV文件')
    else:
        raise ValueError(f'不支持的文件格式: {ext}')

    # 判断tick还是K线数据（使用CTP原始字段名）
    is_tick_data = ('LastPrice' in df.columns or 
                    ('BidPrice1' in df.columns and 'AskPrice1' in df.columns))
    
    if is_tick_data:
        # Tick数据校验 - 必须有datetime和价格字段
        if 'datetime' not in df.columns:
            raise ValueError('Tick数据缺少datetime字段')
        
        # 检查是否有价格字段
        has_price = ('LastPrice' in df.columns or
                     ('BidPrice1' in df.columns and 'AskPrice1' in df.columns))
        if not has_price:
            raise ValueError('Tick数据缺少价格字段（LastPrice/BidPrice1+AskPrice1）')
    else:
        # K线数据校验
        required_columns = ['datetime', 'open', 'high', 'low', 'close']
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            raise ValueError(f'K线数据缺少必要字段: {", ".join(missing_columns)}')
    
    # datetime转为索引
    df['datetime'] = pd.to_datetime(df['datetime'])
    df = df.set_index('datetime')
    df['datetime'] = df.index
    
    # 单文件情况下应用日期筛选
    if start_date is not None or end_date is not None:
        df = filter_by_date_range(df, start_date, end_date)
    
    return df

def filter_by_date_range(df, start_date=None, end_date=None):
    """
    根据日期范围筛选数据
    
    Args:
        df: DataFrame，带有datetime索引
        start_date: 开始日期，格式为"YYYY-MM-DD"
        end_date: 结束日期，格式为"YYYY-MM-DD"
    
    Returns:
        DataFrame: 筛选后的数据
    """
    if df.empty:
        return df
    
    # 转换日期格式
    if start_date is not None:
        if isinstance(start_date, str):
            start_dt = pd.to_datetime(start_date)
        else:
            start_dt = start_date
    
    if end_date is not None:
        if isinstance(end_date, str):
            end_dt = pd.to_datetime(end_date)
        else:
            end_dt = end_date
    
    # 打印日期筛选信息
    original_count = len(df)
    data_min_date = df.index.min().strftime('%Y-%m-%d') if not df.empty else "无数据"
    data_max_date = df.index.max().strftime('%Y-%m-%d') if not df.empty else "无数据"
    print(f"日期筛选：原始数据共 {original_count} 条，日期范围 {data_min_date} 至 {data_max_date}")
    if start_date:
        print(f"筛选开始日期: {start_date}")
    if end_date:
        print(f"筛选结束日期: {end_date}")
    
    # 应用筛选
    if start_date is not None and end_date is not None:
        filtered_df = df.loc[start_dt:end_dt]
    elif start_date is not None:
        filtered_df = df.loc[start_dt:]
    elif end_date is not None:
        filtered_df = df.loc[:end_dt]
    else:
        filtered_df = df
    
    # 打印筛选结果
    filtered_count = len(filtered_df)
    if filtered_count > 0:
        filtered_min_date = filtered_df.index.min().strftime('%Y-%m-%d')
        filtered_max_date = filtered_df.index.max().strftime('%Y-%m-%d')
        print(f"筛选后数据共 {filtered_count} 条，日期范围 {filtered_min_date} 至 {filtered_max_date}")
    else:
        print(f"筛选后数据为空")
    
    return filtered_df 