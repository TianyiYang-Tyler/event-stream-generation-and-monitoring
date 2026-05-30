"""Custom functions for grocery delivery example."""

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
    # Start new users at 100000 to avoid collision with seeded users (0-50000)
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


def choose_grocery_item_in_stock(context):
    """Choose a grocery item that is in stock.
    
    Grocery categories:
    - Fresh Produce: fruits, vegetables
    - Dairy & Eggs: milk, cheese, yogurt, eggs
    - Meat & Seafood: beef, chicken, fish
    - Frozen Foods: frozen vegetables, ice cream, frozen meals
    - Pantry Staples: rice, pasta, canned goods, oils
    - Beverages: juice, soda, water, coffee
    
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
    
    Format: "Grocery order for {first_name} {last_name} (ID: {user_id}, Phone: {phone}, Email: {email}) 
    shipping to {address}. Item: {item_name}"
    """
    cache = context.get("resource_cache")
    if cache is None:
        raise RuntimeError("resource_cache not available in context")

    attrs = context.get("attributes", {})
    user_id = attrs.get("user_id")
    item_id = attrs.get("item_id")
    shipping_location = attrs.get("shipping_location")

    if user_id is None or item_id is None or shipping_location is None:
        raise ValueError("construct_order_details requires user_id, item_id, shipping_location to be filled first")

    # Lookup user in cache
    user_row = None
    for row in cache.table("Users").values():
        if row.get("user_id") == user_id or row.get("user_id") == int(user_id):
            user_row = row
            break

    if user_row is None:
        raise ValueError(f"User {user_id} not found in cache")

    first_name = user_row.get("first_name", "Unknown")
    last_name = user_row.get("last_name", "Unknown")
    phone = user_row.get("phone", "N/A")
    email = user_row.get("email", "N/A")

    # Lookup product
    product_row = cache.table("Products").get(item_id)
    if product_row is None:
        raise ValueError(f"Product {item_id} not found")

    item_name = product_row.get("name", "Unknown")

    return f"Grocery order for {first_name} {last_name} (ID: {user_id}, Phone: {phone}, Email: {email}) shipping to {shipping_location}. Item: {item_name}"


def generate_grocery_store_location(context):
    """Randomly select a grocery store location.
    
    Uses well-known grocery store chains across different regions.
    """
    grocery_stores = [
        "Whole Foods Market - Downtown",
        "Walmart Supercenter - North Location",
        "Kroger - Central Hub",
        "Safeway Distribution Center - West",
        "Trader Joe's - Midtown",
        "Costco Warehouse - South",
        "Target Fresh - East Bay",
        "Harris Teeter - Regional Hub",
        "Sprouts Farmers Market - Urban",
        "Instacart Hub - Metro Center",
    ]
    return random.choice(grocery_stores)


def get_user_credit_card(context):
    """Look up user's credit card number from cache."""
    cache = context.get("resource_cache")
    if cache is None:
        raise RuntimeError("resource_cache not available in context")

    attrs = context.get("attributes", {})
    user_id = attrs.get("user_id")

    if user_id is None:
        raise ValueError("user_id required for get_user_credit_card")

    # Lookup user in cache
    for row in cache.table("Users").values():
        if row.get("user_id") == user_id or row.get("user_id") == int(user_id):
            return row.get("credit_card_num")

    raise ValueError(f"User {user_id} not found in cache")


def generate_customer_comment(context):
    """Generate rating-dependent customer comment."""
    attrs = context.get("attributes", {})
    rating = attrs.get("customer_rating")

    if rating is None:
        return "No comment"

    try:
        rating_int = int(str(rating).strip())
    except (ValueError, TypeError):
        return "No comment"

    comments = {
        5: [
            "Fresh and high quality!",
            "Fast delivery, items arrived perfectly.",
            "Excellent selection and great prices.",
            "Always satisfied with this grocery service.",
            "Best grocery delivery option available.",
            "Produce was fresh and well-packaged.",
            "Highly recommend to all my friends.",
            "Everything as described and on time.",
            "Great quality products, will order again.",
            "5 stars, couldn't ask for better service.",
            "Amazing variety and quick delivery.",
            "Impressed with the freshness of items.",
            "Will definitely be a regular customer.",
        ],
        4: [
            "Good selection and fair prices.",
            "Mostly satisfied with my order.",
            "Delivery was on time.",
            "Items were in good condition.",
            "Good service overall.",
            "Would order again.",
            "Nice variety of products.",
            "Quick and reliable delivery.",
            "Satisfied with the quality.",
        ],
        3: [
            "It was okay, nothing special.",
            "Average service and selection.",
            "Some items could be fresher.",
            "Acceptable delivery time.",
            "Neither great nor bad.",
            "Could be better, could be worse.",
        ],
        2: [
            "Some items were not as described.",
            "Delivery took longer than expected.",
            "Quality could be improved.",
            "Had a few issues with my order.",
            "Not fully satisfied.",
        ],
        1: [
            "Very disappointed with this order.",
            "Poor quality and late delivery.",
            "Items arrived damaged.",
            "Will not order again.",
            "Terrible experience overall.",
            "Worst grocery delivery service.",
            "Completely unsatisfied.",
        ],
    }

    return random.choice(comments.get(rating_int, ["No comment"]))


def generate_weighted_rating(context, distribution=None):
    """Generate a customer rating based on weighted distribution.
    
    Default right-skewed distribution:
    - 5-star: 50%
    - 4-star: 25%
    - 3-star: 15%
    - 2-star: 7%
    - 1-star: 3%
    """
    if distribution is None:
        distribution = {5: 0.50, 4: 0.25, 3: 0.15, 2: 0.07, 1: 0.03}

    # Build cumulative distribution
    ratings = sorted(distribution.keys(), reverse=True)
    cumulative = []
    total = 0.0
    for rating in ratings:
        total += distribution[rating]
        cumulative.append((total, rating))

    # Generate random value and find rating
    rand_val = random.random()
    for cum_prob, rating in cumulative:
        if rand_val <= cum_prob:
            return rating

    return ratings[-1]
