"""Custom functions for AmazinMart shopping example.

Uses the generic ResourceCache via context["resource_cache"]:
  cache.table(name) -> {pk_value: rowdict}
  cache.next_ids(name), cache.add_row(name, {}), cache.mark_dirty(name, key)
All functions take (context, **params), matching how the generator calls them.
"""

import random
from faker import Faker


def choose_or_generate_user_60_40(context, probability_new=0.4, seeded_max_user_id=None):
    """60% existing seeded user, 40% newly generated user."""
    cache = context.get("resource_cache")
    if cache is None:
        raise RuntimeError("resource_cache not available in context")

    seeded_ids = getattr(cache, "_seeded_user_ids_cache", None)
    if seeded_ids is None:
        seeded_ids = []
        for uid in cache.table("Users").keys():
            if uid is None:
                continue
            try:
                numeric = int(uid) if isinstance(uid, str) else uid
                if seeded_max_user_id is None or numeric <= seeded_max_user_id:
                    seeded_ids.append(uid)
            except (ValueError, TypeError):
                pass
        cache._seeded_user_ids_cache = seeded_ids

    if seeded_ids and random.random() >= probability_new:
        return random.choice(seeded_ids)

    new_user_id, new_id = cache.next_ids("Users")
    new_user_id = 100000 + new_user_id  # avoid colliding with seeded ids
    faker = Faker()
    row = {
        "user_id": new_user_id,
        "id": new_id,
        "first_name": faker.first_name(),
        "last_name": faker.last_name(),
        "email": faker.email(),
        "phone": faker.numerify("###-###-####"),
        "address": faker.address().replace("\n", " "),
        "credit_card_num": faker.numerify("####-####-####-####"),
    }
    cache.add_row("Users", row)
    cache.mark_dirty("Users", new_id)
    return new_user_id


def choose_amazin_item_in_stock(context):
    """Pick a random in-stock product and decrement its stock."""
    cache = context.get("resource_cache")
    if cache is None:
        raise RuntimeError("resource_cache not available in context")

    products = cache.table("Products")
    in_stock = [pid for pid, row in products.items() if (row.get("stock") or 0) > 0]
    if not in_stock:
        raise ValueError("No items in stock")

    chosen_id = random.choice(in_stock)
    row = products[chosen_id]
    row["stock"] = (row.get("stock") or 0) - 1
    cache.mark_dirty("Products", chosen_id)
    return chosen_id


def construct_order_details(context):
    """Build an order_details string from already-filled user/item/location."""
    cache = context.get("resource_cache")
    if cache is None:
        raise RuntimeError("resource_cache not available in context")

    attrs = context.get("attributes", {})
    user_id = attrs.get("user_id")
    item_id = attrs.get("item_id")
    shipping_location = attrs.get("shipping_location")
    if not user_id or not item_id or not shipping_location:
        raise ValueError("construct_order_details needs user_id, item_id, shipping_location first")

    users = cache.table("Users")
    user_row = users.get(user_id)
    if user_row is None and isinstance(user_id, str):
        try:
            user_row = users.get(int(user_id))
        except (ValueError, TypeError):
            user_row = None
    if user_row is None:
        raise ValueError(f"User {user_id} not found in cache")

    first = user_row.get("first_name", "Unknown")
    last = user_row.get("last_name", "User")
    phone = user_row.get("phone", "N/A")
    email = user_row.get("email", "N/A")

    products = cache.table("Products")
    product_row = products.get(item_id)
    if product_row is None and isinstance(item_id, str):
        try:
            product_row = products.get(int(item_id))
        except (ValueError, TypeError):
            product_row = None
    if product_row is None:
        raise ValueError(f"Product {item_id} not found in cache")
    item_name = product_row.get("name", "Unknown Item")

    return (f"Order for {first} {last} (ID: {user_id}, Phone: {phone}, Email: {email}) "
            f"shipping to {shipping_location}. Item: {item_name}")


def generate_warehouse_location(context):
    """Pick a random warehouse location from the Warehouses table."""
    cache = context.get("resource_cache")
    if cache is None:
        raise RuntimeError("resource_cache not available in context")
    warehouses = cache.table("Warehouses")
    ids = list(warehouses.keys())
    if not ids:
        raise ValueError("No warehouses available")
    return warehouses[random.choice(ids)].get("location", "Unknown Warehouse")


def get_user_credit_card(context):
    """Look up the user's credit card from the cache."""
    cache = context.get("resource_cache")
    if cache is None:
        raise RuntimeError("resource_cache not available in context")
    attrs = context.get("attributes", {})
    user_id = attrs.get("user_id")
    if user_id is None:
        raise ValueError("user_id required for get_user_credit_card")
    users = cache.table("Users")
    user_row = users.get(user_id)
    if user_row is None and isinstance(user_id, str):
        try:
            user_row = users.get(int(user_id))
        except (ValueError, TypeError):
            user_row = None
    if user_row is None:
        raise ValueError(f"User {user_id} not found in cache")
    return user_row.get("credit_card_num", "0000-0000-0000-0000")


_COMMENTS = {
    5: ["Excellent service, fast delivery!", "Exactly what I expected — 5 stars.",
        "Great quality, will order again.", "Perfect, highly recommend."],
    4: ["Very good, minor packaging issue.", "Good value, happy overall.",
        "Solid purchase, would buy again."],
    3: ["Okay, arrived later than expected.", "Average, nothing special.",
        "Met expectations, could be better."],
    2: ["Disappointed with item condition.", "Not quite as described."],
    1: ["Terrible experience, missing items.", "Very disappointed, would not recommend."],
}


def generate_customer_comment(context):
    """Return a comment matching the already-filled customer_rating."""
    attrs = context.get("attributes", {})
    rating = attrs.get("customer_rating")
    try:
        rating = int(str(rating).strip())
    except (ValueError, TypeError):
        return "No comment."
    return random.choice(_COMMENTS.get(rating, ["No comment."]))


def generate_weighted_rating(context, distribution=None):
    """Weighted 1-5 rating. distribution comes from params (keys may be str)."""
    if distribution is None:
        distribution = {5: 0.50, 4: 0.25, 3: 0.15, 2: 0.07, 1: 0.03}
    dist = {int(k): float(v) for k, v in distribution.items()}
    ratings = sorted(dist.keys(), reverse=True)
    r = random.random()
    cum = 0.0
    for rating in ratings:
        cum += dist[rating]
        if r <= cum:
            return rating
    return ratings[-1]
