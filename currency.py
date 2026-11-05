"""Display formatting for Nepali rupees.

Display only: payment maths stays in whole paisa and never goes through
these functions. Mirrors frontend/src/lib/currency.js, so the Flask pages
and the React studio show amounts the same way.

    100        -> Rs. 100
    1249.5     -> Rs. 1,249.50
    1250000    -> Rs. 12,50,000   (Nepali lakh grouping)
"""

from decimal import Decimal, ROUND_HALF_UP


def group_digits(digits):
    """Nepali grouping: the last three digits, then pairs (12,50,000)."""
    if len(digits) <= 3:
        return digits

    head, tail = digits[:-3], digits[-3:]
    pairs = []
    while len(head) > 2:
        pairs.insert(0, head[-2:])
        head = head[:-2]
    return ",".join([head] + pairs + [tail])


def format_paisa(paisa):
    """Rs. string for a whole-paisa amount. Paisa show only when present."""
    if paisa is None:
        return ""

    paisa = int(paisa)
    sign = "-" if paisa < 0 else ""
    rupees, cents = divmod(abs(paisa), 100)

    text = group_digits(str(rupees))
    if cents:
        text += f".{cents:02d}"
    return f"Rs. {sign}{text}"


def format_rupees(amount):
    """Rs. string for a rupee amount (e.g. Sticker.price)."""
    if amount is None:
        return ""

    # Via str so a float like 1249.5 isn't skewed by binary rounding
    paisa = (Decimal(str(amount)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return format_paisa(paisa)
