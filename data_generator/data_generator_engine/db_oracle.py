import os
from pathlib import Path

import oracledb


_pool = None
_oracle_client_initialized = False


def _init_oracle_client(config_dir):
    # Initialize the thick/thin client config at most once per process.
    global _oracle_client_initialized
    if _oracle_client_initialized or not config_dir:
        return
    try:
        oracledb.init_oracle_client(config_dir=config_dir)
    except oracledb.Error:
        # Ignore if already initialized or not needed.
        pass
    _oracle_client_initialized = True


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
    wallet_password = "ERSPdatagenerator01!"  # Assuming this is the correct wallet password variable

    if not user or not password or not dsn:
        raise ValueError("Missing user, password, or dsn for the database connection.")

    _init_oracle_client(config_dir)

    connect_kwargs = {
        "user": user,
        "password": password,
        "dsn": dsn,
        "config_dir": config_dir,
        "wallet_location": wallet_location,
        "wallet_password": wallet_password,
    }

    if _pool is None:
        # The optimized generator path uses a single long-lived connection held
        # by ResourceCache, so a small pool is sufficient. A couple of spare
        # connections remain available for any legacy per-call code paths.
        _pool = oracledb.create_pool(**connect_kwargs, min=1, max=3, increment=1)

    return _pool.acquire()


def close_pool():
    """Close the shared connection pool. Safe to call multiple times."""
    global _pool
    if _pool is not None:
        try:
            _pool.close()
        finally:
            _pool = None


class ResourceCache:
    """In-memory cache of Stations / Users / Bikes plus write buffers.

    Built once at the start of a generator run. Reads (station selection,
    bike availability, lookups for name/coords/credit_card/is_member) are
    served from memory. Mutations to availability/capacity and bike status
    happen in memory and are written back to Oracle in a single batched
    flush() at the end of the run.
    """

    def __init__(self, connection):
        self._conn = connection

        # station_id -> dict of station columns (mutated in memory).
        self.stations = {}
        # user_id -> dict of user columns (read-only lookups).
        self.users = {}
        # bike_id -> dict of bike columns (status / station_id mutated in memory).
        self.bikes = {}

        # Track which seeded rows we changed so flush() only writes those.
        self._dirty_station_ids = set()
        self._dirty_bike_ids = set()

        # New users created during the run, inserted in one batch at flush().
        self._new_user_rows = []
        # Running max ids so new users get unique ids without round-trips.
        self._max_user_id = 1000
        self._max_user_pk = 0

    # ------------------------------------------------------------------ load

    def load(self):
        cursor = self._conn.cursor()
        try:
            cursor.execute(
                """
                SELECT station_id, id, name, longitude, latitude,
                       capacity, capacity_available, bikes_available
                FROM Stations
                """
            )
            for row in cursor.fetchall():
                (station_id, sid, name, longitude, latitude,
                 capacity, capacity_available, bikes_available) = row
                self.stations[station_id] = {
                    "station_id": station_id,
                    "id": sid,
                    "name": name,
                    "longitude": float(longitude) if longitude is not None else None,
                    "latitude": float(latitude) if latitude is not None else None,
                    "capacity": capacity,
                    "capacity_available": capacity_available,
                    "bikes_available": bikes_available,
                }

            cursor.execute(
                """
                SELECT user_id, id, credit_card_num, is_member
                FROM Users
                WHERE user_id IS NOT NULL
                """
            )
            for row in cursor.fetchall():
                user_id, pk, credit_card_num, is_member = row
                self.users[user_id] = {
                    "user_id": user_id,
                    "id": pk,
                    "credit_card_num": credit_card_num,
                    "is_member": is_member,
                }
                if user_id is not None and user_id > self._max_user_id:
                    self._max_user_id = user_id
                if pk is not None and pk > self._max_user_pk:
                    self._max_user_pk = pk

            cursor.execute(
                """
                SELECT bike_id, id, station_id, status
                FROM Bikes
                WHERE bike_id IS NOT NULL
                """
            )
            for row in cursor.fetchall():
                bike_id, pk, station_id, status = row
                self.bikes[bike_id] = {
                    "bike_id": bike_id,
                    "id": pk,
                    "station_id": station_id,
                    "status": status,
                }
        finally:
            cursor.close()
        return self

    # --------------------------------------------------------------- mutators

    def mark_station_dirty(self, station_id):
        if station_id in self.stations:
            self._dirty_station_ids.add(station_id)

    def mark_bike_dirty(self, bike_id):
        if bike_id in self.bikes:
            self._dirty_bike_ids.add(bike_id)

    def add_user(self, user_row, is_member, credit_card_num):
        """Register a newly generated user in memory and queue it for insert.

        user_row is the full tuple matching the INSERT column order:
        (id, user_id, first_name, last_name, email, phone,
         credit_card_num, is_member)
        """
        self._new_user_rows.append(user_row)
        user_id = user_row[1]
        pk = user_row[0]
        self.users[user_id] = {
            "user_id": user_id,
            "id": pk,
            "credit_card_num": credit_card_num,
            "is_member": is_member,
        }
        if user_id > self._max_user_id:
            self._max_user_id = user_id
        if pk > self._max_user_pk:
            self._max_user_pk = pk

    def next_user_ids(self):
        """Reserve and return the next (user_id, pk) for a new user."""
        self._max_user_id += 1
        self._max_user_pk += 1
        return self._max_user_id, self._max_user_pk

    # ------------------------------------------------------------------ flush

    def flush(self):
        """Write all buffered new users and dirty station/bike state in
        batched statements, then commit once."""
        cursor = self._conn.cursor()
        try:
            if self._new_user_rows:
                cursor.executemany(
                    """
                    INSERT INTO Users (
                        id, user_id, first_name, last_name, email,
                        phone, credit_card_num, is_member,
                        created_at, updated_at
                    ) VALUES (
                        :1, :2, :3, :4, :5, :6, :7, :8,
                        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                    )
                    """,
                    self._new_user_rows,
                )

            if self._dirty_bike_ids:
                bike_updates = [
                    (
                        self.bikes[bid]["station_id"],
                        self.bikes[bid]["status"],
                        bid,
                    )
                    for bid in self._dirty_bike_ids
                ]
                cursor.executemany(
                    """
                    UPDATE Bikes
                    SET station_id = :1,
                        status = :2
                    WHERE bike_id = :3
                    """,
                    bike_updates,
                )

            if self._dirty_station_ids:
                station_updates = [
                    (
                        self.stations[sid]["bikes_available"],
                        self.stations[sid]["capacity_available"],
                        sid,
                    )
                    for sid in self._dirty_station_ids
                ]
                cursor.executemany(
                    """
                    UPDATE Stations
                    SET bikes_available = :1,
                        capacity_available = :2
                    WHERE station_id = :3
                    """,
                    station_updates,
                )

            self._conn.commit()
        finally:
            cursor.close()

        self._new_user_rows.clear()
        self._dirty_bike_ids.clear()
        self._dirty_station_ids.clear()

    def close(self):
        try:
            self._conn.close()
        except Exception:
            pass
