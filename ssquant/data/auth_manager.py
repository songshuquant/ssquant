"""
鉴权管理器 — 通过 data_server 代理验证用户身份

工作流程：
1. 首次调用 verify_auth() 时，将账号密码发送给 data_server 的鉴权接口
2. data_server 内部转发至 kanpan789.com 完成实际验证（鉴权核心逻辑不在开源框架中）
3. 验证成功后缓存结果（整个运行周期内只验证一次）
"""

import requests
import threading
from typing import List, Optional

# ========== 模块级缓存（进程内单例） ==========
_auth_lock = threading.Lock()
_auth_result = None   # None=未检查, True=通过, False=失败
_auth_message = ""

# 实盘配置合并后的 data_server（含 fallback_servers）；未设置时回退到 _server_config.DATA_SERVER
_effective_data_server: Optional[dict] = None
# 当前 WebSocket 所在端点下标（与 _build_verify_urls 顺序一致），重鉴权时优先该节点的 HTTP
_active_endpoint_index: Optional[int] = None
# 最近一次鉴权成功的端点下标
_last_auth_success_index: Optional[int] = None


def set_effective_data_server(ds: Optional[dict]) -> None:
    """
    设置与 trading_config 合并后的 data_server 字典。
    实盘 run() 在 verify_auth 之前调用，使鉴权 URL 与账户里的 data_server 覆盖一致。
    """
    global _effective_data_server
    _effective_data_server = ds.copy() if ds else None


def set_active_endpoint_index(index: Optional[int]) -> None:
    """由 WSKlineClient 在连接成功时调用，使 HTTP 鉴权与当前 WS 节点一致。"""
    global _active_endpoint_index
    _active_endpoint_index = index


def _data_server_dict() -> dict:
    if _effective_data_server:
        return _effective_data_server
    try:
        from ..config._server_config import DATA_SERVER
        return DATA_SERVER
    except Exception:
        return {'api_url': 'http://121.237.178.245:8086', 'fallback_servers': []}


def _build_verify_urls() -> List[str]:
    """主 api_url + fallback_servers[*].api_url，顺序与 WSKlineClient.ws_urls 一致。"""
    ds = _data_server_dict()
    urls = []
    for base in get_ordered_data_server_api_bases():
        urls.append(f"{base}/api/auth/verify")
    return urls


def get_ordered_data_server_api_bases() -> List[str]:
    """主 api_url 与 fallback_servers[*].api_url 的 HTTP 基址（与鉴权、WS 端点顺序一致）。

    data_server 的 REST（如 /api/futures/history）须与鉴权使用同一套地址；仅配置 fallback、未配顶层 api_url 时仍应能拉取数据。
    """
    ds = _data_server_dict()
    out: List[str] = []
    api = ds.get('api_url')
    if api:
        out.append(api.rstrip('/'))
    for fb in (ds.get('fallback_servers') or []):
        a = fb.get('api_url')
        if a:
            out.append(a.rstrip('/'))
    if not out:
        out.append('http://121.237.178.245:8086')
    return out


def _ordered_verify_indices(n: int) -> List[int]:
    """优先当前 WS 端点，其次上次鉴权成功端点，再按配置顺序。"""
    indices = list(range(n))
    prefer = _active_endpoint_index
    if prefer is not None and 0 <= prefer < n:
        return [prefer] + [i for i in indices if i != prefer]
    if _last_auth_success_index is not None and 0 <= _last_auth_success_index < n:
        p = _last_auth_success_index
        return [p] + [i for i in indices if i != p]
    return indices


def _get_auth_url() -> str:
    """兼容旧代码：返回第一个鉴权地址。"""
    urls = _build_verify_urls()
    return urls[0]


def verify_auth(username: str = None, password: str = None,
                *, endpoint_index: Optional[int] = None) -> bool:
    """
    验证用户身份（普通调用使用缓存；指定 WS 节点时重新请求该节点）
    
    鉴权流程: ssquant → data_server → kanpan789.com
    
    Args:
        username: API账号，为 None 时自动从 trading_config 读取
        password: API密码
        endpoint_index: WS 重连目标节点；指定时重新验证该节点，不用缓存或回退到其他节点
    
    Returns:
        True=鉴权成功, False=鉴权失败
    """
    global _auth_result, _auth_message, _last_auth_success_index
    
    with _auth_lock:
        if endpoint_index is None and _auth_result is not None:
            return _auth_result

        if endpoint_index is not None:
            _auth_result = None
            _auth_message = ""
        
        if username is None or password is None:
            try:
                from ..config.trading_config import get_api_auth
                username, password = get_api_auth()
            except Exception:
                _auth_result = False
                _auth_message = "未配置API账号"
                return False
        
        if not username or not password:
            _auth_result = False
            _auth_message = "API账号或密码为空"
            _print_fail()
            return False
        
        verify_urls = _build_verify_urls()
        if endpoint_index is not None:
            if not 0 <= endpoint_index < len(verify_urls):
                _auth_result = False
                _auth_message = "WS 节点没有对应的 HTTP 鉴权地址"
                return False
            order = [endpoint_index]
        else:
            order = _ordered_verify_indices(len(verify_urls))
        print(f"\n[鉴权] 正在验证账号 {username} ...")
        credential_rejected = False  # 服务端已明确拒绝账号（不再尝试其它节点）
        
        for idx in order:
            auth_url = verify_urls[idx]
            try:
                response = requests.get(
                    auth_url,
                    params={'username': username, 'password': password},
                    timeout=(20, 180),
                )
                data = response.json()
                
                if data.get('authenticated'):
                    _auth_result = True
                    _auth_message = data.get('message', '鉴权成功')
                    _last_auth_success_index = idx
                    print(f"[鉴权] 验证通过 (端点 {idx + 1}/{len(verify_urls)}: {auth_url})\n")
                    return _auth_result
                credential_rejected = True
                _auth_message = data.get('message', f'鉴权失败 (HTTP {response.status_code})')
                break
                
            except requests.Timeout:
                _auth_message = f"连接超时: {auth_url}"
                print(f"[鉴权] {_auth_message}，尝试下一地址...")
            except requests.ConnectionError:
                _auth_message = f"无法连接: {auth_url}"
                print(f"[鉴权] {_auth_message}，尝试下一地址...")
            except Exception as e:
                _auth_message = f"异常: {e}"
                print(f"[鉴权] {auth_url} 请求异常: {e}，尝试下一地址...")
        
        if _auth_result is None:
            _auth_result = False
            if not credential_rejected and len(order) > 1:
                _auth_message = "所有 data_server 鉴权地址均不可用，请检查网络或服务"
            elif not credential_rejected and not _auth_message:
                _auth_message = "无法连接 data_server，请确认服务已启动"
            _print_fail()
        
        return _auth_result


def is_authenticated() -> bool:
    """检查是否已鉴权通过（如果未检查过，自动触发验证）"""
    if _auth_result is None:
        return verify_auth()
    return _auth_result


def get_auth_message() -> str:
    """获取鉴权结果消息"""
    return _auth_message


def reset_auth():
    """重置鉴权状态（用于重新验证）"""
    global _auth_result, _auth_message
    with _auth_lock:
        _auth_result = None
        _auth_message = ""


def _print_fail():
    """打印鉴权失败信息"""
    print(f"[鉴权] 验证失败: {_auth_message}")
    print(f"[鉴权] 请检查 ssquant/config/trading_config.py 中的俱乐部账号(API_USERNAME)和俱乐部密码(API_PASSWORD)")
    print(f"[鉴权] 如有疑问，请联系小松鼠 微信: viquant01\n")
