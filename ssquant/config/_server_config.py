"""Remote market data uses ssquantdata's HTTPS/WSS defaults and environment settings.

Optional ClientConfig overrides belong in data_server['sdk_config'].
Legacy direct-IP URLs, fallback rotation and framework auth caches are retired.
"""

DATA_SERVER = {
    'preload_count': 500,
}
