"""Compatibility entry points backed exclusively by ssquantdata authentication."""
from .sdk_client import configure_data_server, get_sdk_client, close_sdk_clients


_auth_message = ''


def set_effective_data_server(settings):
    configure_data_server(settings)


def verify_auth(username=None, password=None):
    """Validate access through the SDK; login and token renewal belong to the SDK."""
    from ssquantdata import SSQuantDataError
    global _auth_message
    try:
        get_sdk_client(username, password).capabilities(force_refresh=True)
    except SSQuantDataError as exc:
        _auth_message = str(exc)
        return False
    _auth_message = 'ssquantdata 鉴权成功'
    return True


def is_authenticated():
    return verify_auth()


def get_auth_message():
    return _auth_message


def reset_auth():
    global _auth_message
    close_sdk_clients()
    _auth_message = ''
