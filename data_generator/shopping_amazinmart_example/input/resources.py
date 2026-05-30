"""Resources for the AmazinMart example.

Creates and seeds the Users, Products, and Warehouses tables in Oracle.
The generic ResourceCache loads these at generation time; functions read them
via context["resource_cache"] (NOT module globals).
"""

import random
import sys
from pathlib import Path

from faker import Faker

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_generator_engine.db_oracle import get_connection

USERS_COUNT = 30000
PRODUCTS_STOCK_PER_ITEM = 2000
WAREHOUSES_COUNT = 8
SEEDED_MAX_USER_ID = 30000


def _catalog():
    base = [
        (1, "AmazinMart Smart Speaker Mini", "Electronics"), (2, "USB-C Charger 65W", "Electronics"),
        (3, "Wireless Mouse", "Electronics"), (4, "Noise Cancelling Headphones", "Electronics"),
        (5, "Stainless Steel Water Bottle", "Home"), (6, "Memory Foam Pillow", "Home"),
        (7, "LED Desk Lamp", "Home"), (8, "Countertop Blender", "Kitchen"), (9, "Cookware Set", "Kitchen"),
        (10, "Children's Story Book", "Books"), (11, "Mystery Novel", "Books"),
        (12, "Family Board Game", "Toys"), (13, "Building Blocks Set", "Toys"), (14, "Yoga Mat", "Fitness"),
        (15, "Running Shoes", "Clothing"), (16, "Men's T-Shirt", "Clothing"),
        (17, "Women's Jeans", "Clothing"), (18, "Smartphone Case", "Electronics"),
        (19, "Portable Hard Drive", "Electronics"), (20, "Drip Coffee Maker", "Kitchen"),
    ]
    fake = Faker()
    cats = ["Electronics", "Home", "Kitchen", "Books", "Toys", "Clothing", "Fitness"]
    pid = 21
    while len(base) < 100:
        name = fake.word().capitalize() + " " + random.choice(["Accessory", "Pack", "Set", "Pro"])
        base.append((pid, name, random.choice(cats)))
        pid += 1
    return base


def seed_users(conn, num_users=USERS_COUNT):
    fake = Faker()
    cur = conn.cursor()
    try:
        cur.execute("BEGIN EXECUTE IMMEDIATE 'DROP TABLE Users'; EXCEPTION WHEN OTHERS THEN NULL; END;")
        cur.execute("""
            CREATE TABLE Users (
                id NUMBER PRIMARY KEY,
                user_id NUMBER UNIQUE,
                first_name VARCHAR2(120),
                last_name VARCHAR2(120),
                email VARCHAR2(255),
                phone VARCHAR2(40),
                address VARCHAR2(500),
                credit_card_num VARCHAR2(32)
            )
        """)
        rows = []
        for i in range(1, num_users + 1):
            rows.append((i, i, fake.first_name(), fake.last_name(), fake.email(),
                         fake.numerify("###-###-####"), fake.address().replace("\n", " "),
                         fake.numerify("####-####-####-####")))
            if len(rows) >= 5000:
                cur.executemany("INSERT INTO Users (id, user_id, first_name, last_name, email, phone, address, credit_card_num) VALUES (:1,:2,:3,:4,:5,:6,:7,:8)", rows)
                conn.commit(); rows.clear()
        if rows:
            cur.executemany("INSERT INTO Users (id, user_id, first_name, last_name, email, phone, address, credit_card_num) VALUES (:1,:2,:3,:4,:5,:6,:7,:8)", rows)
            conn.commit()
    finally:
        cur.close()


def seed_products(conn, stock_per_item=PRODUCTS_STOCK_PER_ITEM):
    cur = conn.cursor()
    try:
        cur.execute("BEGIN EXECUTE IMMEDIATE 'DROP TABLE Products'; EXCEPTION WHEN OTHERS THEN NULL; END;")
        cur.execute("""
            CREATE TABLE Products (
                id NUMBER PRIMARY KEY,
                name VARCHAR2(200),
                stock NUMBER,
                category VARCHAR2(80)
            )
        """)
        rows = [(p[0], p[1], stock_per_item, p[2]) for p in _catalog()]
        cur.executemany("INSERT INTO Products (id, name, stock, category) VALUES (:1,:2,:3,:4)", rows)
        conn.commit()
    finally:
        cur.close()


def seed_warehouses(conn):
    cur = conn.cursor()
    try:
        cur.execute("BEGIN EXECUTE IMMEDIATE 'DROP TABLE Warehouses'; EXCEPTION WHEN OTHERS THEN NULL; END;")
        cur.execute("""
            CREATE TABLE Warehouses (
                id NUMBER PRIMARY KEY,
                warehouse_id NUMBER UNIQUE,
                location VARCHAR2(255)
            )
        """)
        hubs = [
            "Northeast Hub - Boston, MA", "Mid-Atlantic Hub - Philadelphia, PA",
            "Southeast Hub - Atlanta, GA", "Midwest Hub - Chicago, IL",
            "Central Plains Hub - Dallas, TX", "Southwest Hub - Phoenix, AZ",
            "West Coast Hub - Los Angeles, CA", "Pacific NW Hub - Seattle, WA",
        ][:WAREHOUSES_COUNT]
        rows = [(i + 1, i + 1, loc) for i, loc in enumerate(hubs)]
        cur.executemany("INSERT INTO Warehouses (id, warehouse_id, location) VALUES (:1,:2,:3)", rows)
        conn.commit()
    finally:
        cur.close()


def main():
    conn = get_connection()
    try:
        seed_users(conn)
        seed_products(conn)
        seed_warehouses(conn)
    finally:
        conn.close()
    print("AmazinMart resources seeded.")


if __name__ == "__main__":
    main()
