import os

import oracledb


_pool = None


def _init_oracle_client(config_dir):
    if not config_dir:
        return
    try:
        oracledb.init_oracle_client(config_dir=config_dir)
    except oracledb.Error:
        # Ignore if already initialized or not needed.
        pass


def get_connection():
    global _pool

    user = "appuser"
    password = "ERSPdatagenerator01!"  # Assuming this is the correct password variable
    dsn = "resources_low"
    config_dir = "/Users/annagornyitzki/event-stream-generation-and-monitoring/data_generator_engine/Wallet_resources"
    wallet_location = "/Users/annagornyitzki/event-stream-generation-and-monitoring/data_generator_engine/Wallet_resources"
    wallet_password = "ERSPdatagenerator01!" # Assuming this is the correct wallet password variable

    if not user or not password or not dsn:
        raise ValueError("Missing user, password, or dsn for the database connection.")

    _init_oracle_client(config_dir)

    connect_kwargs = {
        "user": user,
        "password": password,
        "dsn": dsn,
        "config_dir": config_dir,
        "wallet_location": wallet_location,
        "wallet_password": wallet_password
    }

    if _pool is None:
        _pool = oracledb.create_pool(**connect_kwargs, min=1, max=5, increment=1)

    return _pool.acquire()
