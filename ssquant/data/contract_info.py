"""
合约信息服务 - 自动获取和缓存合约参数

功能：
1. 从远程 API 拉取最新合约信息
2. 本地 JSON 缓存（每日更新一次）
3. 根据合约代码自动查询参数
4. 支持主力合约（888）自动映射

使用示例：
    from ssquant.data.contract_info import get_trading_params, get_main_contract
    
    # 获取交易参数
    params = get_trading_params('au2602')
    # {'contract_multiplier': 1000, 'price_tick': 0.02, 'margin_rate': 0.08, ...}
    
    # 获取主力合约代码
    main = get_main_contract('au')
    # 'au2602'
"""

import json
import requests
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Optional, List

# 远程 API 地址
CONTRACT_API_URL = "https://kanpan789.com/api/contract_info_all"

# 缓存文件路径
CACHE_DIR = Path(__file__).parent.parent.parent / "data_cache"
CACHE_FILE = CACHE_DIR / "contract_info_cache.json"
CACHE_EXPIRE_HOURS = 4  # 缓存过期时间（小时）


class ContractInfoService:
    """
    合约信息服务（单例模式）
    
    自动从远程 API 获取合约信息，包括：
    - 合约乘数
    - 最小变动价位
    - 保证金率
    - 手续费率
    - 主力合约标识
    """
    
    _instance = None
    _contracts: Dict[str, Dict] = {}  # 合约代码 -> 合约信息
    _varieties: Dict[str, Dict] = {}  # 品种代码 -> 主力合约信息
    _last_update: Optional[datetime] = None
    _initialized: bool = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not self._initialized:
            self._initialized = True
            self._load_or_fetch()
    
    def _load_or_fetch(self):
        """加载缓存或从远程获取"""
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        
        # 检查缓存是否有效
        if self._is_cache_valid():
            self._load_from_cache()
        else:
            self._fetch_from_api()
    
    def _is_cache_valid(self) -> bool:
        """检查缓存是否有效"""
        if not CACHE_FILE.exists():
            return False
        
        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            update_time_str = data.get('update_time', '2000-01-01T00:00:00')
            update_time = datetime.fromisoformat(update_time_str)
            if datetime.now() - update_time > timedelta(hours=CACHE_EXPIRE_HOURS):
                return False
            
            return True
        except Exception:
            return False
    
    def _load_from_cache(self):
        """从缓存加载"""
        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            self._process_contracts(data.get('contracts', []))
            update_time_str = data.get('update_time', '')
            if update_time_str:
                self._last_update = datetime.fromisoformat(update_time_str)
            print(f"[合约信息] 从缓存加载 {len(self._contracts)} 个合约")
        except Exception as e:
            print(f"[合约信息] 缓存加载失败: {e}，尝试远程获取")
            self._fetch_from_api()
    
    def _fetch_from_api(self):
        """从远程 API 获取"""
        try:
            print(f"[合约信息] 正在从远程获取合约数据...")
            response = requests.get(CONTRACT_API_URL, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            if not data.get('success', False):
                raise ValueError(f"API 返回错误: {data.get('error')}")
            
            contracts = data.get('contracts', [])
            self._process_contracts(contracts)
            
            # 保存到缓存
            cache_data = {
                'update_time': datetime.now().isoformat(),
                'contracts': contracts
            }
            with open(CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)
            
            self._last_update = datetime.now()
            print(f"[合约信息] 已获取并缓存 {len(self._contracts)} 个合约")
            
        except Exception as e:
            print(f"[合约信息] 远程获取失败: {e}")
            # 尝试使用过期缓存
            if CACHE_FILE.exists():
                print("[合约信息] 尝试使用过期缓存")
                try:
                    with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    self._process_contracts(data.get('contracts', []))
                    print(f"[合约信息] 从过期缓存加载 {len(self._contracts)} 个合约")
                except Exception:
                    print("[合约信息] 缓存不可用，将使用默认参数")
    
    def _process_contracts(self, contracts: List[Dict]):
        """处理合约数据"""
        self._contracts.clear()
        self._varieties.clear()
        
        for c in contracts:
            code = c.get('合约代码', '')
            if not code:
                continue
            
            # 存储合约信息（多种大小写格式）
            self._contracts[code] = c
            self._contracts[code.upper()] = c
            self._contracts[code.lower()] = c
            
            # 处理主力合约
            variety = c.get('品种代码', '')
            if c.get('主力标识') == '主力' and variety:
                self._varieties[variety] = c
                self._varieties[variety.upper()] = c
                self._varieties[variety.lower()] = c
                
                # 创建 888 映射（主力连续）
                main_symbol = f"{variety}888"
                self._contracts[main_symbol] = c
                self._contracts[main_symbol.upper()] = c
                self._contracts[main_symbol.lower()] = c
            
            # 处理次主力合约（777 映射）
            if c.get('主力标识') == '次主力' and variety:
                sub_symbol = f"{variety}777"
                self._contracts[sub_symbol] = c
                self._contracts[sub_symbol.upper()] = c
                self._contracts[sub_symbol.lower()] = c
    
    def get_contract_info(self, symbol: str) -> Optional[Dict]:
        """
        获取合约完整信息
        
        Args:
            symbol: 合约代码，支持：
                - 具体合约: "au2602", "rb2505"
                - 主力连续: "au888", "rb888"
                - 次主力连续: "au777", "rb777"
                - 品种代码: "au", "rb"（返回主力合约）
        
        Returns:
            合约信息字典，未找到返回 None
        """
        # 直接查找
        if symbol in self._contracts:
            return self._contracts[symbol]
        
        # 尝试品种代码
        if symbol in self._varieties:
            return self._varieties[symbol]
        
        # 尝试提取品种代码（去除数字）
        variety = ''.join(c for c in symbol if c.isalpha())
        if variety in self._varieties:
            return self._varieties[variety]
        
        return None
    
    def get_trading_params(self, symbol: str) -> Dict:
        """
        获取交易参数（直接可用于 ssquant 配置）
        
        Args:
            symbol: 合约代码
        
        Returns:
            包含交易参数的字典：
            - contract_multiplier: 合约乘数
            - price_tick: 最小变动价位
            - margin_rate: 保证金率
            - commission: 开仓手续费率
            - commission_close: 平仓手续费率
            - commission_close_today: 平今手续费率
            - exchange: 交易所代码
            - variety_name: 品种名称
            - is_main_contract: 是否为主力合约
            - actual_symbol: 实际合约代码（主力连续会解析为具体合约）
        """
        info = self.get_contract_info(symbol)
        
        if info:
            actual_symbol = info.get('合约代码', symbol)
            return {
                'contract_multiplier': info.get('合约乘数', 10),
                'price_tick': info.get('最小跳动', 1.0),
                'margin_rate': info.get('做多保证金率', 0.1),
                # 费率型手续费
                'commission': info.get('开仓费率', 0.0001),
                'commission_close': info.get('平仓费率', 0.0001),
                'commission_close_today': info.get('平今费率', 0.0001),
                # 固定金额手续费（元/手）- 优先使用
                'commission_per_lot': info.get('1手开仓费用', 0),
                'commission_close_per_lot': info.get('1手平仓费用', 0),
                'commission_close_today_per_lot': info.get('1手平今费用', 0),
                # 额外信息
                'exchange': info.get('交易所', ''),
                'variety_name': info.get('品种名称', ''),
                'is_main_contract': info.get('主力标识', '') == '主力',
                'actual_symbol': actual_symbol,
                'latest_price': info.get('最新价', 0),
                'margin_per_lot': info.get('做多1手保证金', 0),
            }
        
        # 未找到时返回默认值
        print(f"[合约信息] 警告：未找到 {symbol} 的合约信息，使用默认参数")
        return {
            'contract_multiplier': 10,
            'price_tick': 1.0,
            'margin_rate': 0.1,
            # 费率型手续费
            'commission': 0.0001,
            'commission_close': 0.0001,
            'commission_close_today': 0.0001,
            # 固定金额手续费（元/手）
            'commission_per_lot': 0,
            'commission_close_per_lot': 0,
            'commission_close_today_per_lot': 0,
            'exchange': '',
            'variety_name': '',
            'is_main_contract': False,
            'actual_symbol': symbol,
            'latest_price': 0,
            'margin_per_lot': 0,
        }
    
    def get_main_contract(self, variety: str) -> Optional[str]:
        """
        获取品种的主力合约代码
        
        Args:
            variety: 品种代码，如 "au", "rb"
        
        Returns:
            主力合约代码，如 "au2602"，未找到返回 None
        """
        info = self._varieties.get(variety) or self._varieties.get(variety.lower())
        if info:
            return info.get('合约代码')
        return None
    
    def get_sub_main_contract(self, variety: str) -> Optional[str]:
        """
        获取品种的次主力合约代码
        
        Args:
            variety: 品种代码，如 "au", "rb"
        
        Returns:
            次主力合约代码，未找到返回 None
        """
        sub_symbol = f"{variety}777"
        info = self._contracts.get(sub_symbol) or self._contracts.get(sub_symbol.lower())
        if info:
            return info.get('合约代码')
        return None
    
    def list_varieties(self) -> List[Dict]:
        """
        列出所有品种及其主力合约
        
        Returns:
            品种列表，每个元素包含品种信息
        """
        seen = set()
        result = []
        for variety, info in self._varieties.items():
            code = info.get('合约代码', '')
            if code not in seen:
                seen.add(code)
                result.append({
                    'variety': info.get('品种代码', ''),
                    'variety_name': info.get('品种名称', ''),
                    'main_contract': code,
                    'exchange': info.get('交易所', ''),
                    'contract_multiplier': info.get('合约乘数', 10),
                    'price_tick': info.get('最小跳动', 1.0),
                })
        return sorted(result, key=lambda x: x['variety'])
    
    def refresh(self):
        """强制刷新合约信息"""
        self._fetch_from_api()
    
    @property
    def last_update(self) -> Optional[datetime]:
        """获取最后更新时间"""
        return self._last_update
    
    @property
    def contract_count(self) -> int:
        """获取合约数量"""
        return len(set(c.get('合约代码') for c in self._contracts.values() if c.get('合约代码')))


# ==================== 便捷函数 ====================

_service: Optional[ContractInfoService] = None


def get_contract_service() -> ContractInfoService:
    """获取合约信息服务实例"""
    global _service
    if _service is None:
        _service = ContractInfoService()
    return _service


def get_trading_params(symbol: str) -> Dict:
    """
    获取合约交易参数（便捷函数）
    
    Args:
        symbol: 合约代码，如 "au2602", "au888", "au"
    
    Returns:
        交易参数字典
    
    示例:
        params = get_trading_params('au2602')
        print(params['contract_multiplier'])  # 1000
        print(params['price_tick'])           # 0.02
    """
    return get_contract_service().get_trading_params(symbol)


def get_main_contract(variety: str) -> Optional[str]:
    """
    获取主力合约代码（便捷函数）
    
    Args:
        variety: 品种代码，如 "au", "rb"
    
    Returns:
        主力合约代码，如 "au2602"
    
    示例:
        main = get_main_contract('au')
        print(main)  # 'au2602'
    """
    return get_contract_service().get_main_contract(variety)


def get_contract_info(symbol: str) -> Optional[Dict]:
    """
    获取合约完整信息（便捷函数）
    
    Args:
        symbol: 合约代码
    
    Returns:
        合约信息字典
    """
    return get_contract_service().get_contract_info(symbol)


def refresh_contracts():
    """强制刷新合约信息（便捷函数）"""
    get_contract_service().refresh()


def list_varieties() -> List[Dict]:
    """列出所有品种（便捷函数）"""
    return get_contract_service().list_varieties()


# ==================== 命令行工具 ====================

if __name__ == '__main__':
    import sys
    
    service = get_contract_service()
    
    if len(sys.argv) > 1:
        symbol = sys.argv[1]
        params = get_trading_params(symbol)
        print(f"\n合约 {symbol} 的交易参数：")
        print("-" * 40)
        for key, value in params.items():
            print(f"  {key}: {value}")
    else:
        print("\n所有品种列表：")
        print("-" * 60)
        print(f"{'品种':<8} {'名称':<10} {'主力合约':<10} {'乘数':<8} {'跳动':<8} {'交易所'}")
        print("-" * 60)
        for v in list_varieties():
            print(f"{v['variety']:<8} {v['variety_name']:<10} {v['main_contract']:<10} "
                  f"{v['contract_multiplier']:<8} {v['price_tick']:<8} {v['exchange']}")
        print("-" * 60)
        print(f"共 {len(list_varieties())} 个品种")
