import os
from pathlib import Path

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
    wallet_dir = Path(__file__).resolve().parent / "Wallet_resources"
    config_dir = str(wallet_dir)
    wallet_location = str(wallet_dir)
    tns_admin = os.environ.get("TNS_ADMIN")
    if not tns_admin or not Path(tns_admin).exists():
        os.environ["TNS_ADMIN"] = str(wallet_dir)
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
