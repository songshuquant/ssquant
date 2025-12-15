"""
合约映射器
用于处理主连合约（如rb888）与具体合约（如rb2601）之间的映射关系
"""

import re
from typing import Optional


class ContractMapper:
    """主连合约与具体合约的映射管理器"""
    
    # 品种代码提取规则（字母部分）
    SYMBOL_PATTERN = r'^([a-zA-Z]+)\d*'
    
    # 主连后缀（常用的主连合约后缀）
    CONTINUOUS_SUFFIXES = ['888', '777', '000']
    
    @classmethod
    def extract_product_code(cls, symbol: str) -> str:
        """
        提取品种代码（字母部分）
        
        Args:
            symbol: 合约代码
            
        Returns:
            品种代码（小写）
            
        Examples:
            >>> ContractMapper.extract_product_code('rb2601')
            'rb'
            >>> ContractMapper.extract_product_code('au2512')
            'au'
            >>> ContractMapper.extract_product_code('IF2503')
            'if'
        """
        match = re.match(cls.SYMBOL_PATTERN, symbol)
        if match:
            return match.group(1).lower()
        return symbol.lower()
    
    @classmethod
    def is_continuous(cls, symbol: str) -> bool:
        """
        判断是否为主连合约
        
        Args:
            symbol: 合约代码
            
        Returns:
            是否为主连合约
            
        Examples:
            >>> ContractMapper.is_continuous('rb888')
            True
            >>> ContractMapper.is_continuous('rb2601')
            False
        """
        for suffix in cls.CONTINUOUS_SUFFIXES:
            if symbol.endswith(suffix):
                return True
        return False
    
    @classmethod
    def get_continuous_symbol(cls, specific_contract: str) -> str:
        """
        从具体合约推导主连符号（简化版方案）
        
        规则：提取品种代码 + 888
        
        Args:
            specific_contract: 具体合约代码
            
        Returns:
            主连合约代码
            
        Examples:
            >>> ContractMapper.get_continuous_symbol('rb2601')
            'rb888'
            >>> ContractMapper.get_continuous_symbol('au2512')
            'au888'
            >>> ContractMapper.get_continuous_symbol('IF2503')
            'if888'
        """
        # 如果本身就是主连，直接返回
        if cls.is_continuous(specific_contract):
            return specific_contract.lower()
        
        # 提取品种代码
        product_code = cls.extract_product_code(specific_contract)
        
        # 拼接888后缀
        return f"{product_code}888"
    
    @classmethod
    def get_product_info(cls, symbol: str) -> dict:
        """
        获取合约的详细信息
        
        Args:
            symbol: 合约代码
            
        Returns:
            包含合约信息的字典
            
        Examples:
            >>> ContractMapper.get_product_info('rb2601')
            {'product_code': 'rb', 'is_continuous': False, 'continuous_symbol': 'rb888'}
        """
        return {
            'product_code': cls.extract_product_code(symbol),
            'is_continuous': cls.is_continuous(symbol),
            'continuous_symbol': cls.get_continuous_symbol(symbol),
        }


if __name__ == '__main__':
    # 测试代码
    test_symbols = ['rb2601', 'au2512', 'IF2503', 'rb888', 'au000']
    
    print("=" * 60)
    print("合约映射器测试")
    print("=" * 60)
    
    for symbol in test_symbols:
        info = ContractMapper.get_product_info(symbol)
        print(f"\n合约: {symbol}")
        print(f"  品种代码: {info['product_code']}")
        print(f"  是否主连: {info['is_continuous']}")
        print(f"  主连符号: {info['continuous_symbol']}")

