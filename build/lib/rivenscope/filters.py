"""Safe, bounded filter AST with SQL-like unknown propagation."""
import operator
from .domain import Listing, finite

FIELDS = {
    "weapon": "text", "category": "text", "price": "number", "kind": "text",
    "seller_status": "text", "rank": "number", "mastery": "number", "rerolls": "number",
    "polarity": "text", "positive_count": "number", "negative_count": "number",
    "discount": "number", "profit": "number", "confidence": "number", "platform": "text",
    "crossplay": "bool", "reputation": "number",
}
OPS = ("eq", "ne", "gt", "ge", "lt", "le", "exists", "absent", "contains", "in")
COMPARE = {"eq": operator.eq, "ne": operator.ne, "gt": operator.gt, "ge": operator.ge,
           "lt": operator.lt, "le": operator.le}


def field_type(name):
    if name in FIELDS:
        return FIELDS[name]
    if isinstance(name, str) and name.startswith(("positive.", "negative.", "attribute.")) and len(name.split(".", 1)[1]) <= 120:
        return "number"
    raise ValueError("Unknown filter field")


def validate(expression, catalog=None, category=None, depth=0, budget=None):
    budget = [0] if budget is None else budget
    budget[0] += 1
    if depth > 12 or budget[0] > 200 or not isinstance(expression, dict):
        raise ValueError("Filter too large or invalid (12 levels / 200 nodes maximum)")
    op = expression.get("op")
    if op in ("AND", "OR", "NOT"):
        children = expression.get("children")
        if not isinstance(children, list) or (op == "NOT" and len(children) != 1):
            raise ValueError("NOT requires exactly one condition")
        if op == "OR" and not children:
            raise ValueError("OR requires at least one condition")
        for child in children:
            validate(child, catalog, category, depth + 1, budget)
        return
    name = expression.get("field")
    kind = field_type(name)
    if op not in OPS:
        raise ValueError("Invalid filter operator")
    if "." in name and catalog is not None:
        sign, slug = name.split(".", 1)
        attribute = catalog.get(slug)
        if attribute is None:
            raise ValueError(f"Unknown Riven attribute: {slug}")
        if category and attribute.get("exclusiveTo") and category not in attribute["exclusiveTo"]:
            raise ValueError(f"{slug} is not applicable to {category}")
        if (sign == "negative" and attribute.get("positiveOnly")) or (sign == "positive" and attribute.get("negativeOnly")):
            raise ValueError(f"{slug} does not support this sign")
    if op in ("exists", "absent"):
        return
    value = expression.get("value")
    values = value if op == "in" else [value]
    if not isinstance(values, list) or not values or len(values) > 1000:
        raise ValueError("Invalid filter values")
    if op == "contains" and kind != "text":
        raise ValueError("Contains requires a text field")
    for item in values:
        if kind == "number":
            finite(item, "Filter value")
        elif kind == "bool":
            if type(item) is not bool:
                raise ValueError("Expected boolean")
        elif not isinstance(item, str) or len(item) > 300:
            raise ValueError("Expected short text")


def field_value(listing, field, estimate=None):
    if "." in field:
        sign, slug = field.split(".", 1)
        for a in listing.attributes:
            if a.slug == slug and (sign == "attribute" or a.positive == (sign == "positive")):
                return a.value
        return None
    if field == "positive_count":
        return sum(a.positive for a in listing.attributes)
    if field == "negative_count":
        return sum(not a.positive for a in listing.attributes)
    if field in ("discount", "profit", "confidence"):
        return getattr(estimate, field, None) if estimate and estimate.status != "Insufficient data" else None
    if field == "price":
        return listing.acquisition  # starting bids must not masquerade as an acquisition price
    return getattr(listing, field, None)


def evaluate(expression, listing: Listing, estimate=None):
    op = expression["op"]
    if op in ("AND", "OR", "NOT"):
        values = [evaluate(c, listing, estimate) for c in expression["children"]]
        if op == "NOT":
            return None if values[0] is None else not values[0]
        if op == "AND":
            return False if False in values else None if None in values else True
        return True if True in values else None if None in values else False
    value = field_value(listing, expression["field"], estimate)
    if op == "exists":
        return value is not None
    if op == "absent":
        return value is None
    if value is None:
        return None
    wanted = expression.get("value")
    if op == "contains":
        return wanted.casefold() in value.casefold()
    if op == "in":
        return value in wanted
    return COMPARE[op](value, wanted)


def matches(expression, listing, estimate=None):
    return evaluate(expression, listing, estimate) is True


def server_plan(expression):
    """No server predicates until a contract API is documented. Never invent query params."""
    validate(expression)
    return {"available": False, "requests": [], "local": expression}
