"""Share the official SDK between remote history, authentication and realtime."""
import atexit
from dataclasses import replace
import os
import threading


_lock = threading.Lock()
_settings = {}
_clients = {}


def configure_data_server(settings=None):
    """Framework settings use sdk_config overrides, not legacy HTTP/WS nodes."""
    global _settings
    if any(key in (settings or {}) for key in ('api_url', 'ws_url', 'fallback_servers')):
        raise ValueError('旧 data_server 地址配置已停用，请使用 sdk_config 或 SSQUANTDATA_* 环境变量')
    with _lock:
        _settings = dict(settings or {})


def get_sdk_client(username=None, password=None):
    """Reuse SDK token refresh and connections for the same account/configuration."""
    from ssquantdata import ClientConfig, SSQuantDataClient

    explicit_credentials = username is not None or password is not None
    if username is None:
        username = os.getenv('SSQUANTDATA_USERNAME')
    if password is None:
        password = os.getenv('SSQUANTDATA_PASSWORD')
    # Explicit credentials must never reuse another account's environment token.
    access_token = None if explicit_credentials else os.getenv('SSQUANTDATA_ACCESS_TOKEN')
    refresh_token = None if explicit_credentials else os.getenv('SSQUANTDATA_REFRESH_TOKEN')
    if not access_token and (username is None or password is None):
        from ..config.trading_config import get_api_auth
        configured_username, configured_password = get_api_auth()
        if username is None:
            username = configured_username
        if password is None:
            password = configured_password

    with _lock:
        config = replace(ClientConfig.from_env(), **_settings.get('sdk_config', {}))
        key = (username, password, access_token, refresh_token, config)
        if key not in _clients:
            _clients[key] = SSQuantDataClient(
                username=username, password=password,
                access_token=access_token, refresh_token=refresh_token, config=config,
            )
        return _clients[key]


def close_sdk_clients():
    """Release SDK resources at process shutdown or explicit account reset."""
    with _lock:
        clients = list(_clients.values())
        _clients.clear()
    for client in clients:
        client.close()


atexit.register(close_sdk_clients)


def history_frame(symbol, period, *, username=None, password=None, preload=False,
                  start_date=None, end_date=None, start_time=None, end_time=None,
                  limit=None):
    """Return raw SDK records as the framework's datetime-indexed DataFrame."""
    import pandas as pd
    from ssquantdata import InvalidServerResponseError

    result = get_sdk_client(username, password).futures.history(
        symbol, period, start_date=start_date, end_date=end_date,
        start_time=start_time, end_time=end_time, limit=limit,
        preload=preload, cache=False,
    )
    if result.status != 'ok':
        raise InvalidServerResponseError(result.message)
    if not result.records:
        return pd.DataFrame(index=pd.DatetimeIndex([], name='datetime'))
    frame = pd.DataFrame(result.records)
    if 'datetime' not in frame:
        raise InvalidServerResponseError('history records are missing datetime')
    frame['datetime'] = pd.to_datetime(frame['datetime'])
    frame = frame.set_index('datetime')
    return frame[~frame.index.duplicated(keep='last')].sort_index()
