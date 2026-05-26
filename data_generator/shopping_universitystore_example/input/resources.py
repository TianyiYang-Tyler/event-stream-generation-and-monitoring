"""Resources for university shopping example.

Provides Users and Products master data for the generator.
Uses the shared Oracle connection handler from db_oracle.
"""

import sys
from pathlib import Path

from faker import Faker

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_generator_engine.db_oracle import get_connection

# ============================================================================
# Configuration for data generation
# ============================================================================
# Estimate for 100,000 events:
#   - ~13 events per order (Order, Confirm_payment, AddItem, Ship, Confirm_arrival x2,
#     Delivery_out, Confirm_delivery, Rate_order x2 for each of 2 Delivery cycles)
#   - 100,000 / 13 ≈ 7,700 orders
#   - With 60% existing users from seeded pool, 20,000 seeded users gives good coverage
#   - Each product needs ~770 stock (7,700 orders * 2 items / 20 products)
# ============================================================================

USERS_COUNT = 20000              # Seeded users (60/40 split with generated)
PRODUCTS_STOCK_PER_ITEM = 800    # Stock per product (to support ~100k events)
WAREHOUSES_COUNT = 5             # Regional warehouse hubs
SEEDED_MAX_USER_ID = 20000       # Used in 60/40 split logic

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_generator_engine.db_oracle import get_connection


def seed_users(conn, num_users=None):
    """Seed Users table with pre-seeded users for 60/40 split."""
    if num_users is None:
        num_users = USERS_COUNT
    
    cursor = conn.cursor()
    fake = Faker()
    try:
        # Drop existing table
        cursor.execute("BEGIN EXECUTE IMMEDIATE 'DROP TABLE Users'; EXCEPTION WHEN OTHERS THEN NULL; END;", {})
        
        # Create table
        cursor.execute("""
            CREATE TABLE Users (
                id NUMBER PRIMARY KEY,
                user_id VARCHAR2(10) NOT NULL,
                first_name VARCHAR2(120),
                last_name VARCHAR2(120),
                email VARCHAR2(255),
                phone VARCHAR2(40),
                address VARCHAR2(255),
                credit_card_num VARCHAR2(20),
                UNIQUE (user_id)
            )
        """)
        
        # Generate all users upfront (faster than generating during insert)
        users_data = []
        for i in range(num_users):
            users_data.append((
                i,
                i,  # user_id is just numeric
                fake.first_name(),
                fake.last_name(),
                fake.email(),
                fake.numerify("###-###-####"),
                fake.address().replace("\n", " "),
                fake.numerify("####-####-####-####")  # Simple credit card format
            ))
        
        # Batch insert all users at once (much faster than loop of individual INSERTs)
        cursor.executemany("""
            INSERT INTO Users (id, user_id, first_name, last_name, email, phone, address, credit_card_num)
            VALUES (:1, :2, :3, :4, :5, :6, :7, :8)
        """, users_data)
        
        conn.commit()
    finally:
        cursor.close()


def seed_products(conn, stock_per_item=None):
    """Seed Products table with university shop items."""
    if stock_per_item is None:
        stock_per_item = PRODUCTS_STOCK_PER_ITEM
    
    cursor = conn.cursor()
    try:
        # Drop existing table
        cursor.execute("BEGIN EXECUTE IMMEDIATE 'DROP TABLE Products'; EXCEPTION WHEN OTHERS THEN NULL; END;", {})
        
        # Create table
        cursor.execute("""
            CREATE TABLE Products (
                id NUMBER PRIMARY KEY,
                name VARCHAR2(100) NOT NULL,
                stock NUMBER NOT NULL,
                category VARCHAR2(50)
            )
        """)
        # Insert university shop items with parameterized stock
        products = [
            # Merch (5 items)
            (1, "University T-Shirt", stock_per_item, "Merch"),
            (2, "University Hoodie", stock_per_item, "Merch"),
            (3, "University Hat", stock_per_item, "Merch"),
            (4, "University Sweatshirt", stock_per_item, "Merch"),
            (5, "University Socks", stock_per_item, "Merch"),
            # Decor (4 items)
            (6, "University Poster", stock_per_item, "Decor"),
            (7, "University Flag", stock_per_item, "Decor"),
            (8, "University Banner", stock_per_item, "Decor"),
            (9, "University Pennant", stock_per_item, "Decor"),
            # Textbooks (5 items)
            (10, "Introduction to Computer Science", stock_per_item, "Textbooks"),
            (11, "Calculus I", stock_per_item, "Textbooks"),
            (12, "Biology 101", stock_per_item, "Textbooks"),
            (13, "Chemistry Essentials", stock_per_item, "Textbooks"),
            (14, "English Composition", stock_per_item, "Textbooks"),
            # School Supplies (6 items)
            (15, "Notebook Pack", stock_per_item, "School Supplies"),
            (16, "Pen Set", stock_per_item, "School Supplies"),
            (17, "Pencil Pack", stock_per_item, "School Supplies"),
            (18, "Folder Set", stock_per_item, "School Supplies"),
            (19, "Sticky Notes", stock_per_item, "School Supplies"),
            (20, "Calculator", stock_per_item, "School Supplies"),
        ]
        cursor.executemany("""
            INSERT INTO Products (id, name, stock, category)
            VALUES (:1, :2, :3, :4)
        """, products)
        conn.commit()
    finally:
        cursor.close()


def seed_warehouses(conn):
    """Seed Warehouses table with regional warehouse locations."""
    cursor = conn.cursor()
    try:
        # Drop existing table
        cursor.execute("BEGIN EXECUTE IMMEDIATE 'DROP TABLE Warehouses'; EXCEPTION WHEN OTHERS THEN NULL; END;", {})
        
        # Create table
        cursor.execute("""
            CREATE TABLE Warehouses (
                id NUMBER PRIMARY KEY,
                warehouse_id VARCHAR2(20) NOT NULL,
                location VARCHAR2(255),
                UNIQUE (warehouse_id)
            )
        """)
        
        # Insert warehouse locations
        warehouses = [
            (1, "warehouse_01", "Northeast Regional Hub - Boston, MA"),
            (2, "warehouse_02", "Midwest Regional Hub - Chicago, IL"),
            (3, "warehouse_03", "Southwest Regional Hub - Dallas, TX"),
            (4, "warehouse_04", "West Coast Hub - Los Angeles, CA"),
            (5, "warehouse_05", "Southeast Regional Hub - Atlanta, GA"),
        ]
        cursor.executemany("""
            INSERT INTO Warehouses (id, warehouse_id, location)
            VALUES (:1, :2, :3)
        """, warehouses)
        
        conn.commit()
    finally:
        cursor.close()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Seed university shopping example resources"
    )
    parser.add_argument(
        "--users",
        type=int,
        default=USERS_COUNT,
        help=f"Number of seeded users (default: {USERS_COUNT})"
    )
    parser.add_argument(
        "--stock",
        type=int,
        default=PRODUCTS_STOCK_PER_ITEM,
        help=f"Stock per product (default: {PRODUCTS_STOCK_PER_ITEM})"
    )
    
    args = parser.parse_args()
    
    conn = get_connection()
    seed_users(conn, num_users=args.users)
    seed_products(conn, stock_per_item=args.stock)
    seed_warehouses(conn)
    conn.close()
    print("Resources seeded successfully.")
