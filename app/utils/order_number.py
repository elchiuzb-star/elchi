from uuid import uuid4


def generate_order_number() -> str:
    return f"ORD-{uuid4().hex[:10].upper()}"
