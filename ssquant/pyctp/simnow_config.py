#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
SIMNOW 服务器配置模块
提供SIMNOW各服务器的配置信息
"""

from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class SIMNOWServer:
    """SIMNOW服务器配置"""
    name: str
    trader_front: str
    md_front: str
    description: str
    broker_id: str = '9999'
    app_id: str = 'simnow_client_test'
    auth_code: str = '0000000000000000'


class SIMNOWConfig:
    """SIMNOW配置管理类"""
    
    def __init__(self):
        # SIMNOW服务器列表 - 使用真实的服务器配置
        self.servers = {
            # 电信1服务器
            '电信1': SIMNOWServer(
                name='电信1',
                trader_front='tcp://182.254.243.31:30001',
                md_front='tcp://182.254.243.31:30011',
                description='电信线路1服务器',
                broker_id='9999',
                app_id='simnow_client_test',
                auth_code='0000000000000000'
            ),
            
            # 电信2服务器
            '电信2': SIMNOWServer(
                name='电信2',
                trader_front='tcp://182.254.243.31:30002',
                md_front='tcp://182.254.243.31:30012',
                description='电信线路2服务器',
                broker_id='9999',
                app_id='simnow_client_test',
                auth_code='0000000000000000'
            ),
            
            # 移动服务器
            '移动': SIMNOWServer(
                name='移动',
                trader_front='tcp://218.202.237.33:10203',
                md_front='tcp://218.202.237.33:10213',
                description='移动线路服务器',
                broker_id='9999',
                app_id='simnow_client_test',
                auth_code='0000000000000000'
            ),
            
            # TEST服务器
            'TEST': SIMNOWServer(
                name='TEST',
                trader_front='tcp://182.254.243.31:40001',
                md_front='tcp://182.254.243.31:40011',
                description='TEST服务器',
                broker_id='9999',
                app_id='simnow_client_test',
                auth_code='0000000000000000'
            ),
            
            # N视界服务器
            'N视界': SIMNOWServer(
                name='N视界',
                trader_front='tcp://210.14.72.12:4600',
                md_front='tcp://210.14.72.12:4602',
                description='N视界服务器',
                broker_id='10010',
                app_id='',
                auth_code=''
            ),
            
            # 默认7x24小时环境
            '24hour': SIMNOWServer(
                name='7x24小时环境',
                trader_front='tcp://180.168.146.187:10130',
                md_front='tcp://180.168.146.187:10131',
                description='7x24小时连续交易环境，适合全天候测试',
                broker_id='9999',
                app_id='simnow_client_test',
                auth_code='0000000000000000'
            ),
        }
    
    def get_server(self, server_name: str) -> Optional[SIMNOWServer]:
        """
        获取服务器配置
        :param server_name: 服务器名称
        :return: 服务器配置对象
        """
        return self.servers.get(server_name)
    
    def list_servers(self) -> Dict[str, SIMNOWServer]:
        """
        列出所有服务器
        :return: 服务器字典
        """
        return self.servers
    
    def print_servers(self):
        """打印所有服务器信息"""
        print("=" * 80)
        print("SIMNOW 服务器列表")
        print("=" * 80)
        for name, server in self.servers.items():
            print(f"\n【{name}】 - {server.description}")
            print(f"  交易前置: {server.trader_front}")
            print(f"  行情前置: {server.md_front}")
            print(f"  经纪商ID: {server.broker_id}")
            if server.app_id:
                print(f"  应用ID:   {server.app_id}")
        print("=" * 80)


# 账号配置模板
SIMNOW_ACCOUNT_TEMPLATE = {
    "investor_id": "",  # Simnow的账号
    "password": "",     # Simnow的密码
    "server_name": "24hour",  # 服务器名称（电信1, 电信2, 移动, TEST, N视界, 24hour）
    "subscribe_list": [b'au2506', b'rb2501'],  # 订阅合约列表
    "md_flow_path": "simnow_md_flow/",
    "td_flow_path": "simnow_td_flow/",
}

# 实盘账号模板
REAL_ACCOUNT_TEMPLATE = {
    "broker_id": "",
    "server_dict": {
        "TDServer": "tcp://ip:port",
        "MDServer": "tcp://ip:port"
    },
    "reserve_server_dict": {},
    "investor_id": "",
    "password": "",
    "app_id": "your_app_id",
    "auth_code": "your_auth_code",
    "subscribe_list": [b'au2506'],
    "md_flow_path": "real_md_flow/",
    "td_flow_path": "real_td_flow/",
}


if __name__ == '__main__':
    # 打印服务器信息
    config = SIMNOWConfig()
    config.print_servers()

