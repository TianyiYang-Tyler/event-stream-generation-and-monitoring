"""Custom functions for university shopping example."""

import random
from faker import Faker


def choose_or_generate_user_60_40(context, probability_new=0.4, seeded_max_user_id=None):
    """Choose 60% existing user, 40% new user (inverse of probability_new).
    
    - 60% existing: pick from seeded Users table
    - 40% new: generate new user_id and insert into Users table
    """
    cache = context.get("resource_cache")
    if cache is None:
        raise RuntimeError("resource_cache not available in context")

    # Build seeded user pool on first call
    seeded_ids = getattr(cache, "_seeded_user_ids_cache", None)
    if seeded_ids is None:
        seeded_ids = []
        for uid in cache.table("Users").keys():
            if uid is not None:
                try:
                    # Convert to int for comparison (handles both int and string types)
                    numeric_uid = int(uid) if isinstance(uid, str) else uid
                    if seeded_max_user_id is None or numeric_uid <= seeded_max_user_id:
                        seeded_ids.append(uid)
                except (ValueError, TypeError):
                    pass
        cache._seeded_user_ids_cache = seeded_ids

    # 60% existing (1 - 0.4 = 0.6), 40% new
    if seeded_ids and random.random() >= probability_new:
        return random.choice(seeded_ids)

    # Generate new user
    new_user_id, new_id = cache.next_ids("Users")
    # Start new users at 100000 to avoid collision with seeded users (0-20000)
    new_user_id = 100000 + new_user_id
    
    faker = Faker()
    first_name = faker.first_name()
    last_name = faker.last_name()
    email = faker.email()
    phone = faker.numerify("###-###-####")
    address = faker.address().replace("\n", " ")
    credit_card_num = faker.numerify("####-####-####-####")

    row = {
        "user_id": new_user_id,
        "id": new_id,
        "first_name": first_name,
        "last_name": last_name,
        "email": email,
        "phone": phone,
        "address": address,
        "credit_card_num": credit_card_num,
    }
    cache.add_row("Users", row)
    cache.mark_dirty("Users", new_id)
    return new_user_id


def choose_university_item_in_stock(context):
    """Choose a university shop item that is in stock.
    
    University shop categories:
    - Merch: t-shirts, hoodies, sweatshirts, hats, caps
    - Decor: posters, banners, flags, wall art
    - Textbooks: various subject textbooks
    - School Supplies: notebooks, pens, pencils, folders
    
    Picks randomly from in-stock items and decrements stock.
    """
    cache = context.get("resource_cache")
    if cache is None:
        raise RuntimeError("resource_cache not available in context")

    products = cache.table("Products")
    in_stock = [item_id for item_id, row in products.items()
                if row.get("stock", 0) > 0]

    if not in_stock:
        raise ValueError("No items in stock")

    chosen_id = random.choice(in_stock)
    row = products[chosen_id]

    # Decrement stock
    new_stock = (row.get("stock", 0) or 0) - 1
    row["stock"] = new_stock
    cache.mark_dirty("Products", chosen_id)

    return chosen_id


def construct_order_details(context):
    """Construct order_details string from user, address, and item info.
    
    Format: "Order for {Name} ({email}) shipping to {address}. Item: {item_name}"
    """
    attributes = context.get("attributes", {})
    cache = context.get("resource_cache")
    runtime_state = context.get("runtime_state")

    if cache is None:
        raise RuntimeError("resource_cache not available in context")

    user_id = attributes.get("user_id")
    item_id = attributes.get("item_id")
    shipping_location = attributes.get("shipping_location")

    if not user_id or not item_id or not shipping_location:
        raise ValueError("Missing required attributes: user_id, item_id, shipping_location")

    # Lookup user email from cache
    users = cache.table("Users")
    user_row = users.get(user_id)
    if user_row is None:
        raise ValueError(f"User {user_id} not found in cache")

    first_name = user_row.get("first_name", "Unknown")
    last_name = user_row.get("last_name", "User")
    email = user_row.get("email", "unknown@university.edu")
    phone = user_row.get("phone", "000-000-0000")

    # Lookup item name from cache
    products = cache.table("Products")
    product_row = products.get(item_id)
    if product_row is None:
        raise ValueError(f"Product {item_id} not found in cache")

    item_name = product_row.get("name", "Unknown Item")

    # Construct order details with full user info
    order_details = (
        f"Order for {first_name} {last_name} (ID: {user_id}, Phone: {phone}, Email: {email}) "
        f"shipping to {shipping_location}. Item: {item_name}"
    )

    return order_details


def generate_warehouse_location(context):
    """Generate a random warehouse location for order confirmation at warehouse."""
    cache = context.get("resource_cache")
    if cache is None:
        raise RuntimeError("resource_cache not available in context")

    warehouses = cache.table("Warehouses")
    warehouse_ids = list(warehouses.keys())
    
    if not warehouse_ids:
        raise ValueError("No warehouses available in cache")
    
    chosen_id = random.choice(warehouse_ids)
    warehouse = warehouses[chosen_id]
    return warehouse.get("location", "Unknown Warehouse")


def get_user_credit_card(context):
    """Get credit_card_num for a user from the resource cache.
    
    Looks up the user by user_id and returns their credit card number.
    Works for both seeded and newly generated users (that exist in cache).
    """
    attributes = context.get("attributes", {})
    cache = context.get("resource_cache")
    
    if cache is None:
        raise RuntimeError("resource_cache not available in context")
    
    user_id = attributes.get("user_id")
    if user_id is None:
        raise ValueError("user_id not available in context")
    
    users = cache.table("Users")
    user_row = users.get(user_id)
    
    if user_row is None:
        raise ValueError(f"User {user_id} not found in cache")
    
    return user_row.get("credit_card_num", "0000-0000-0000-0000")


def generate_customer_comment(context):
    """Generate a customer comment about the order based on the rating.
    
    Comments vary by star rating:
    - 5 stars: Highly positive
    - 4 stars: Positive
    - 3 stars: Mixed/neutral
    - 1 star: Negative
    """
    attributes = context.get("attributes", {})
    rating = attributes.get("customer_rating")
    
    if rating is None:
        raise ValueError("customer_rating not available in context")
    
    # Comments by rating tier
    comments_by_rating = {
        5: [
            "Great quality, fast delivery!",
            "Perfect! Exactly what I needed.",
            "Excellent service, will order again.",
            "Very satisfied with my purchase.",
            "Highly recommend!",
            "Great experience, thank you!",
            "Product exceeded expectations.",
            "Very impressed with the quality.",
            "Fantastic! Five stars!",
            "Amazing customer service.",
            "Will definitely be a repeat customer.",
            "Love it! Best purchase ever.",
            "Outstanding quality and service.",
        ],
        4: [
            "Good quality and fair price.",
            "Satisfied with the product.",
            "Fast shipping, happy customer.",
            "Pretty good overall.",
            "Nice product, good value.",
            "Would recommend to friends.",
            "Generally very pleased.",
            "Quality is decent.",
            "Good experience overall.",
        ],
        3: [
            "It's okay, nothing special.",
            "Acceptable product.",
            "Average quality.",
            "Could be better.",
            "Met my expectations.",
            "Decent product for the price.",
        ],
        1: [
            "Not what I expected.",
            "Poor quality.",
            "Disappointed with purchase.",
            "Would not recommend.",
            "Quality is subpar.",
            "Not satisfied.",
            "Very disappointed.",
        ],
    }
    
    comments = comments_by_rating.get(rating, comments_by_rating[1])
    return random.choice(comments)


def generate_weighted_rating(context, distribution=None):
    """Generate a customer rating with weighted distribution from params.
    
    Args:
        distribution: Dict mapping rating (1-5) to probability (should sum to 1.0)
        Example: {5: 0.50, 4: 0.25, 3: 0.15, 2: 0.07, 1: 0.03}
    
    Default distribution (if not provided):
    50% → 5 stars
    25% → 4 stars
    15% → 3 stars
    7% → 2 stars
    3% → 1 star
    """
    if distribution is None:
        distribution = {5: 0.50, 4: 0.25, 3: 0.15, 2: 0.07, 1: 0.03}
    
    # Convert distribution dict to cumulative probabilities
    ratings = sorted(distribution.keys(), reverse=True)  # 5, 4, 3, 2, 1
    cumulative = 0.0
    cumulative_dist = {}
    for rating in ratings:
        cumulative += distribution[rating]
        cumulative_dist[rating] = cumulative
    
    rand = random.random()
    for rating in ratings:
        if rand < cumulative_dist[rating]:
            return rating
    
    # Fallback (shouldn't happen if distribution sums to 1.0)
    return 1
