def format_service_price(price: int, price_max: int | None = None) -> str:
    """Format a fixed service price or a price range for display."""
    lower = f"{price:,}".replace(",", " ")
    if price_max is not None:
        upper = f"{price_max:,}".replace(",", " ")
        return f"от {lower} до {upper} ₽"
    return f"{lower} ₽"
