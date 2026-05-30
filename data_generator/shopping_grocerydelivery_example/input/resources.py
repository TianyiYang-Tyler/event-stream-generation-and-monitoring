"""Seed resources for grocery delivery example."""

from __future__ import annotations

import argparse
import random
import sys
from datetime import datetime
from pathlib import Path

from faker import Faker

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_generator_engine.db_oracle import get_connection

# Configuration parameters
USERS_COUNT = 50000              # Seeded users (60/40 split with generated)
PRODUCTS_STOCK_PER_ITEM = 5000   # Stock per product (high for grocery)
WAREHOUSES_COUNT = 10             # Regional distribution centers
SEEDED_MAX_USER_ID = 50000       # Used in 60/40 split logic


def seed_users(conn, num_users=None):
    """Seed Users table with pre-seeded users for 60/40 split."""
    if num_users is None:
        num_users = USERS_COUNT
    
    cursor = conn.cursor()
    try:
        # Drop existing table
        cursor.execute("BEGIN EXECUTE IMMEDIATE 'DROP TABLE Users'; EXCEPTION WHEN OTHERS THEN NULL; END;", {})
        
        # Create table
        cursor.execute("""
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
        
        # Generate users with Faker
        fake = Faker()
        user_rows = []
        for i in range(1, num_users + 1):
            user_rows.append((
                i,
                i,
                fake.first_name(),
                fake.last_name(),
                fake.email(),
                fake.numerify("###-###-####"),
                fake.address().replace("\n", " "),
                fake.numerify("####-####-####-####"),
            ))
        
        cursor.executemany("""
            INSERT INTO Users (id, user_id, first_name, last_name, email, phone, address, credit_card_num)
            VALUES (:1, :2, :3, :4, :5, :6, :7, :8)
        """, user_rows)
        conn.commit()
        print(f"Seeded {num_users} users")
    finally:
        cursor.close()


def seed_products(conn, stock_per_item=None):
    """Seed Products table with grocery items."""
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
        
        # Comprehensive grocery product list with realistic items
        products = [
            # Fresh Produce (IDs 1-30)
            (1, "Bananas", stock_per_item, "Fresh Produce"),
            (2, "Apples (Gala)", stock_per_item, "Fresh Produce"),
            (3, "Oranges", stock_per_item, "Fresh Produce"),
            (4, "Strawberries", stock_per_item, "Fresh Produce"),
            (5, "Broccoli", stock_per_item, "Fresh Produce"),
            (6, "Carrots", stock_per_item, "Fresh Produce"),
            (7, "Lettuce (Romaine)", stock_per_item, "Fresh Produce"),
            (8, "Tomatoes", stock_per_item, "Fresh Produce"),
            (9, "Cucumbers", stock_per_item, "Fresh Produce"),
            (10, "Bell Peppers", stock_per_item, "Fresh Produce"),
            (11, "Onions", stock_per_item, "Fresh Produce"),
            (12, "Potatoes", stock_per_item, "Fresh Produce"),
            (13, "Sweet Potatoes", stock_per_item, "Fresh Produce"),
            (14, "Spinach", stock_per_item, "Fresh Produce"),
            (15, "Garlic", stock_per_item, "Fresh Produce"),
            (16, "Blueberries", stock_per_item, "Fresh Produce"),
            (17, "Grapes", stock_per_item, "Fresh Produce"),
            (18, "Lemons", stock_per_item, "Fresh Produce"),
            (19, "Limes", stock_per_item, "Fresh Produce"),
            (20, "Avocados", stock_per_item, "Fresh Produce"),
            (21, "Mushrooms", stock_per_item, "Fresh Produce"),
            (22, "Cabbage", stock_per_item, "Fresh Produce"),
            (23, "Kale", stock_per_item, "Fresh Produce"),
            (24, "Zucchini", stock_per_item, "Fresh Produce"),
            (25, "Corn", stock_per_item, "Fresh Produce"),
            (26, "Green Beans", stock_per_item, "Fresh Produce"),
            (27, "Peas", stock_per_item, "Fresh Produce"),
            (28, "Peaches", stock_per_item, "Fresh Produce"),
            (29, "Watermelon", stock_per_item, "Fresh Produce"),
            (30, "Cantaloupe", stock_per_item, "Fresh Produce"),
            
            # Dairy & Eggs (IDs 31-50)
            (31, "Whole Milk (Gallon)", stock_per_item, "Dairy & Eggs"),
            (32, "2% Milk (Gallon)", stock_per_item, "Dairy & Eggs"),
            (33, "Skim Milk (Gallon)", stock_per_item, "Dairy & Eggs"),
            (34, "Greek Yogurt", stock_per_item, "Dairy & Eggs"),
            (35, "Regular Yogurt", stock_per_item, "Dairy & Eggs"),
            (36, "Cottage Cheese", stock_per_item, "Dairy & Eggs"),
            (37, "Cheddar Cheese (Shredded)", stock_per_item, "Dairy & Eggs"),
            (38, "Mozzarella Cheese", stock_per_item, "Dairy & Eggs"),
            (39, "Parmesan Cheese", stock_per_item, "Dairy & Eggs"),
            (40, "Butter", stock_per_item, "Dairy & Eggs"),
            (41, "Cream Cheese", stock_per_item, "Dairy & Eggs"),
            (42, "Eggs (Dozen)", stock_per_item, "Dairy & Eggs"),
            (43, "Brown Eggs (Dozen)", stock_per_item, "Dairy & Eggs"),
            (44, "Sour Cream", stock_per_item, "Dairy & Eggs"),
            (45, "Heavy Cream", stock_per_item, "Dairy & Eggs"),
            (46, "Milk Chocolate Yogurt", stock_per_item, "Dairy & Eggs"),
            (47, "String Cheese", stock_per_item, "Dairy & Eggs"),
            (48, "Feta Cheese", stock_per_item, "Dairy & Eggs"),
            (49, "Swiss Cheese", stock_per_item, "Dairy & Eggs"),
            (50, "Almond Milk", stock_per_item, "Dairy & Eggs"),
            
            # Meat & Seafood (IDs 51-70)
            (51, "Ground Beef (1 lb)", stock_per_item, "Meat & Seafood"),
            (52, "Chicken Breast", stock_per_item, "Meat & Seafood"),
            (53, "Chicken Thighs", stock_per_item, "Meat & Seafood"),
            (54, "Ground Turkey", stock_per_item, "Meat & Seafood"),
            (55, "Salmon Fillet", stock_per_item, "Meat & Seafood"),
            (56, "Tilapia Fillet", stock_per_item, "Meat & Seafood"),
            (57, "Shrimp", stock_per_item, "Meat & Seafood"),
            (58, "Pork Chops", stock_per_item, "Meat & Seafood"),
            (59, "Ground Pork", stock_per_item, "Meat & Seafood"),
            (60, "Bacon", stock_per_item, "Meat & Seafood"),
            (61, "Sausage Links", stock_per_item, "Meat & Seafood"),
            (62, "Turkey Breast", stock_per_item, "Meat & Seafood"),
            (63, "Ham Slices", stock_per_item, "Meat & Seafood"),
            (64, "Deli Turkey", stock_per_item, "Meat & Seafood"),
            (65, "Deli Roast Beef", stock_per_item, "Meat & Seafood"),
            (66, "Steak (Ribeye)", stock_per_item, "Meat & Seafood"),
            (67, "Lamb Chops", stock_per_item, "Meat & Seafood"),
            (68, "Cod Fillet", stock_per_item, "Meat & Seafood"),
            (69, "Crab Legs", stock_per_item, "Meat & Seafood"),
            (70, "Beef Hot Dogs", stock_per_item, "Meat & Seafood"),
            
            # Frozen Foods (IDs 71-90)
            (71, "Frozen Broccoli", stock_per_item, "Frozen Foods"),
            (72, "Frozen Mixed Vegetables", stock_per_item, "Frozen Foods"),
            (73, "Frozen Peas", stock_per_item, "Frozen Foods"),
            (74, "Frozen Corn", stock_per_item, "Frozen Foods"),
            (75, "Frozen Pizza", stock_per_item, "Frozen Foods"),
            (76, "Frozen Burritos", stock_per_item, "Frozen Foods"),
            (77, "Frozen Fried Chicken", stock_per_item, "Frozen Foods"),
            (78, "Ice Cream (Vanilla)", stock_per_item, "Frozen Foods"),
            (79, "Ice Cream (Chocolate)", stock_per_item, "Frozen Foods"),
            (80, "Frozen Berries", stock_per_item, "Frozen Foods"),
            (81, "Frozen Spinach", stock_per_item, "Frozen Foods"),
            (82, "Frozen French Fries", stock_per_item, "Frozen Foods"),
            (83, "Frozen Mozzarella Sticks", stock_per_item, "Frozen Foods"),
            (84, "Frozen Fish Fillets", stock_per_item, "Frozen Foods"),
            (85, "Frozen Shrimp", stock_per_item, "Frozen Foods"),
            (86, "Frozen Lasagna", stock_per_item, "Frozen Foods"),
            (87, "Frozen Dumplings", stock_per_item, "Frozen Foods"),
            (88, "Frozen Pies", stock_per_item, "Frozen Foods"),
            (89, "Frozen Waffles", stock_per_item, "Frozen Foods"),
            (90, "Frozen Yogurt", stock_per_item, "Frozen Foods"),
            
            # Pantry Staples (IDs 91-120)
            (91, "White Rice (1 lb)", stock_per_item, "Pantry Staples"),
            (92, "Brown Rice", stock_per_item, "Pantry Staples"),
            (93, "Pasta (Penne)", stock_per_item, "Pantry Staples"),
            (94, "Pasta (Spaghetti)", stock_per_item, "Pantry Staples"),
            (95, "Cereal (Corn Flakes)", stock_per_item, "Pantry Staples"),
            (96, "Cereal (Oatmeal)", stock_per_item, "Pantry Staples"),
            (97, "Bread (Whole Wheat)", stock_per_item, "Pantry Staples"),
            (98, "Bread (White)", stock_per_item, "Pantry Staples"),
            (99, "Tortillas", stock_per_item, "Pantry Staples"),
            (100, "Peanut Butter", stock_per_item, "Pantry Staples"),
            (101, "Jelly", stock_per_item, "Pantry Staples"),
            (102, "Canned Beans", stock_per_item, "Pantry Staples"),
            (103, "Canned Tomatoes", stock_per_item, "Pantry Staples"),
            (104, "Canned Soup", stock_per_item, "Pantry Staples"),
            (105, "Canned Tuna", stock_per_item, "Pantry Staples"),
            (106, "Olive Oil", stock_per_item, "Pantry Staples"),
            (107, "Vegetable Oil", stock_per_item, "Pantry Staples"),
            (108, "Flour", stock_per_item, "Pantry Staples"),
            (109, "Sugar", stock_per_item, "Pantry Staples"),
            (110, "Honey", stock_per_item, "Pantry Staples"),
            (111, "Salt", stock_per_item, "Pantry Staples"),
            (112, "Black Pepper", stock_per_item, "Pantry Staples"),
            (113, "Baking Powder", stock_per_item, "Pantry Staples"),
            (114, "Baking Soda", stock_per_item, "Pantry Staples"),
            (115, "Vanilla Extract", stock_per_item, "Pantry Staples"),
            (116, "Soy Sauce", stock_per_item, "Pantry Staples"),
            (117, "Ketchup", stock_per_item, "Pantry Staples"),
            (118, "Mustard", stock_per_item, "Pantry Staples"),
            (119, "Mayo", stock_per_item, "Pantry Staples"),
            (120, "Salad Dressing", stock_per_item, "Pantry Staples"),
            
            # Beverages (IDs 121-150)
            (121, "Orange Juice (Gallon)", stock_per_item, "Beverages"),
            (122, "Apple Juice", stock_per_item, "Beverages"),
            (123, "Grape Juice", stock_per_item, "Beverages"),
            (124, "Cranberry Juice", stock_per_item, "Beverages"),
            (125, "Lemonade", stock_per_item, "Beverages"),
            (126, "Coca-Cola (6-pack)", stock_per_item, "Beverages"),
            (127, "Sprite (6-pack)", stock_per_item, "Beverages"),
            (128, "Root Beer (6-pack)", stock_per_item, "Beverages"),
            (129, "Sparkling Water", stock_per_item, "Beverages"),
            (130, "Sports Drink", stock_per_item, "Beverages"),
            (131, "Iced Tea", stock_per_item, "Beverages"),
            (132, "Coffee (Grounds)", stock_per_item, "Beverages"),
            (133, "Coffee Beans", stock_per_item, "Beverages"),
            (134, "Tea Bags", stock_per_item, "Beverages"),
            (135, "Hot Chocolate Mix", stock_per_item, "Beverages"),
            (136, "Beer (6-pack)", stock_per_item, "Beverages"),
            (137, "Wine (Red)", stock_per_item, "Beverages"),
            (138, "Wine (White)", stock_per_item, "Beverages"),
            (139, "Champagne", stock_per_item, "Beverages"),
            (140, "Bottled Water (24-pack)", stock_per_item, "Beverages"),
            (141, "Coconut Water", stock_per_item, "Beverages"),
            (142, "Almond Milk (Quart)", stock_per_item, "Beverages"),
            (143, "Oat Milk", stock_per_item, "Beverages"),
            (144, "Soy Milk", stock_per_item, "Beverages"),
            (145, "Kombucha", stock_per_item, "Beverages"),
            (146, "Energy Drink", stock_per_item, "Beverages"),
            (147, "Gatorade", stock_per_item, "Beverages"),
            (148, "Smoothie Mix", stock_per_item, "Beverages"),
            (149, "Protein Shake", stock_per_item, "Beverages"),
            (150, "Vitamin Water", stock_per_item, "Beverages"),
        ]
        
        cursor.executemany("""
            INSERT INTO Products (id, name, stock, category)
            VALUES (:1, :2, :3, :4)
        """, products)
        conn.commit()
        print(f"Seeded {len(products)} products")
    finally:
        cursor.close()


def seed_warehouses(conn):
    """Seed Warehouses table with grocery distribution centers."""
    cursor = conn.cursor()
    try:
        # Drop existing table
        cursor.execute("BEGIN EXECUTE IMMEDIATE 'DROP TABLE Warehouses'; EXCEPTION WHEN OTHERS THEN NULL; END;", {})
        
        # Create table
        cursor.execute("""
            CREATE TABLE Warehouses (
                id NUMBER PRIMARY KEY,
                warehouse_id NUMBER UNIQUE,
                location VARCHAR2(255)
            )
        """)
        
        # Regional distribution centers for grocery delivery
        warehouses = [
            (1, 1, "Northeast Regional Hub - Boston, MA"),
            (2, 2, "Mid-Atlantic Hub - Philadelphia, PA"),
            (3, 3, "Southeast Hub - Atlanta, GA"),
            (4, 4, "Midwest Hub - Chicago, IL"),
            (5, 5, "Central Plains Hub - Dallas, TX"),
            (6, 6, "Southwest Hub - Phoenix, AZ"),
            (7, 7, "West Coast Hub - Los Angeles, CA"),
            (8, 8, "Pacific Northwest Hub - Seattle, WA"),
            (9, 9, "Mountain Region Hub - Denver, CO"),
            (10, 10, "Florida Hub - Miami, FL"),
        ]
        
        cursor.executemany("""
            INSERT INTO Warehouses (id, warehouse_id, location)
            VALUES (:1, :2, :3)
        """, warehouses)
        conn.commit()
        print(f"Seeded {len(warehouses)} warehouses")
    finally:
        cursor.close()


def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Seed grocery delivery example resources"
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


if __name__ == "__main__":
    main()
