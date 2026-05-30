import os
from pathlib import Path

try:
    import oracledb
except ImportError:  # allow local testing without the oracle driver installed
    oracledb = None


_pool = None
_oracle_client_initialized = False


def _init_oracle_client(config_dir):
    global _oracle_client_initialized
    if _oracle_client_initialized or not config_dir or oracledb is None:
        return
    try:
        oracledb.init_oracle_client(config_dir=config_dir)
    except oracledb.Error:
        pass
    _oracle_client_initialized = True


def get_connection():
    global _pool
    if oracledb is None:
        raise RuntimeError("oracledb is not installed in this environment")

    user = "appuser"
    password = "ERSPdatagenerator01!"
    dsn = "resources_low"
    wallet_dir = Path(__file__).resolve().parent / "Wallet_resources"
    config_dir = str(wallet_dir)
    wallet_location = str(wallet_dir)
    tns_admin = os.environ.get("TNS_ADMIN")
    if not tns_admin or not Path(tns_admin).exists():
        os.environ["TNS_ADMIN"] = str(wallet_dir)
    wallet_password = "ERSPdatagenerator01!"

    _init_oracle_client(config_dir)
    connect_kwargs = {
        "user": user, "password": password, "dsn": dsn,
        "config_dir": config_dir, "wallet_location": wallet_location,
        "wallet_password": wallet_password,
    }
    if _pool is None:
        _pool = oracledb.create_pool(**connect_kwargs, min=1, max=3, increment=1)
    return _pool.acquire()


def close_pool():
    global _pool
    if _pool is not None:
        try:
            _pool.close()
        finally:
            _pool = None


class TableSpec:
    """Describes one table the cache should manage, from the fill_spec
    `resources.tables` block."""

    def __init__(self, name, cfg):
        self.name = name
        self.columns = list(cfg.get("columns", []))
        # The key functions use to address rows (e.g. user_id). Defaults to the
        # surrogate pk_column if not given.
        self.pk_column = cfg.get("pk_column", "id")
        self.primary_key = cfg.get("primary_key", self.pk_column)
        self.insertable = bool(cfg.get("insertable", False))
        self.id_sequence = bool(cfg.get("id_sequence", False))
        # Columns written back on UPDATE for dirty rows (subset of columns).
        self.mutable_columns = list(cfg.get("mutable_columns", []))
        # Optional WHERE filter applied at load.
        self.where = cfg.get("where")

    def select_sql(self):
        cols = ", ".join(self.columns)
        sql = f"SELECT {cols} FROM {self.name}"
        if self.where:
            sql += f" WHERE {self.where}"
        return sql


class ResourceCache:
    """Schema-generic in-memory cache.

    Tables to load/manage come from the fill_spec `resources.tables` block,
    passed in as `schema`. Each table is held as {key_value: {col: val}} where
    key_value is the table's `primary_key` column value. Functions interact
    through a uniform API: table(), add_row(), next_ids(), mark_dirty().
    """

    def __init__(self, connection, schema=None):
        self._conn = connection
        self._specs = {}
        self._tables = {}        # name -> {pk_value: rowdict}
        self._dirty = {}         # name -> set(pk_value)
        self._new_rows = {}      # name -> list(rowdict)
        self._max_pk = {}        # name -> {primary_key: max, pk_column: max}

        if schema:
            self.configure(schema)

    # ----------------------------------------------------------- configuration
    def configure(self, schema):
        tables = (schema or {}).get("tables", {})
        for name, cfg in tables.items():
            spec = TableSpec(name, cfg)
            self._specs[name] = spec
            self._tables[name] = {}
            self._dirty[name] = set()
            self._new_rows[name] = []
            self._max_pk[name] = {"primary_key": 0, "pk_column": 0}
        return self

    # ------------------------------------------------------------------- load
    def load(self):
        cursor = self._conn.cursor()
        try:
            for name, spec in self._specs.items():
                cursor.execute(spec.select_sql())
                col_index = {c: i for i, c in enumerate(spec.columns)}
                for row in cursor.fetchall():
                    rowdict = {c: row[col_index[c]] for c in spec.columns}
                    key = rowdict.get(spec.primary_key)
                    if key is None:
                        continue
                    self._tables[name][key] = rowdict
                    self._track_max(name, spec, rowdict)
        finally:
            cursor.close()
        return self

    def _track_max(self, name, spec, rowdict):
        pk_val = rowdict.get(spec.primary_key)
        surrogate = rowdict.get(spec.pk_column)
        m = self._max_pk[name]
        if isinstance(pk_val, (int, float)) and pk_val > m["primary_key"]:
            m["primary_key"] = pk_val
        if isinstance(surrogate, (int, float)) and surrogate > m["pk_column"]:
            m["pk_column"] = surrogate

    # ----------------------------------------------------------- generic API
    def table(self, name):
        """Return the {pk_value: rowdict} mapping for a table."""
        if name not in self._tables:
            raise KeyError(f"Table not configured in resources: {name}")
        return self._tables[name]

    def next_ids(self, name):
        """Reserve and return (primary_key, pk_column) for a new row."""
        spec = self._specs[name]
        if not spec.id_sequence:
            raise ValueError(f"Table {name} is not configured with id_sequence")
        m = self._max_pk[name]
        m["primary_key"] += 1
        m["pk_column"] += 1
        return m["primary_key"], m["pk_column"]

    def add_row(self, name, rowdict):
        """Register a new row in memory and queue it for insert at flush()."""
        spec = self._specs[name]
        if not spec.insertable:
            raise ValueError(f"Table {name} is not insertable")
        key = rowdict.get(spec.primary_key)
        self._tables[name][key] = rowdict
        self._new_rows[name].append(rowdict)
        self._track_max(name, spec, rowdict)

    def mark_dirty(self, name, key):
        if key in self._tables.get(name, {}):
            self._dirty[name].add(key)

    # ------------------------------------------------------------------ flush
    def flush(self):
        cursor = self._conn.cursor()
        try:
            for name, spec in self._specs.items():
                # inserts
                rows = self._new_rows[name]
                if rows and spec.insertable:
                    cols = spec.columns
                    placeholders = ", ".join(f":{i+1}" for i in range(len(cols)))
                    col_list = ", ".join(cols)
                    data = [tuple(r.get(c) for c in cols) for r in rows]
                    cursor.executemany(
                        f"INSERT INTO {name} ({col_list}) VALUES ({placeholders})",
                        data,
                    )
                # updates for dirty rows
                dirty = self._dirty[name]
                if dirty and spec.mutable_columns:
                    set_cols = spec.mutable_columns
                    set_clause = ", ".join(
                        f"{c} = :{i+1}" for i, c in enumerate(set_cols)
                    )
                    where_idx = len(set_cols) + 1
                    updates = [
                        tuple(self._tables[name][k].get(c) for c in set_cols)
                        + (k,)
                        for k in dirty
                    ]
                    cursor.executemany(
                        f"UPDATE {name} SET {set_clause} "
                        f"WHERE {spec.primary_key} = :{where_idx}",
                        updates,
                    )
            self._conn.commit()
        finally:
            cursor.close()
        for name in self._specs:
            self._new_rows[name].clear()
            self._dirty[name].clear()

    def close(self):
        try:
            self._conn.close()
        except Exception:
            pass
