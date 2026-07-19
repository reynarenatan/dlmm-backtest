"""Bin math for Meteora DLMM pools.

Prices in a DLMM pool live in discrete bins. Neighboring bins are spaced
by a fixed percentage (the "bin step", in basis points), so bin prices
form a geometric sequence: price(i) = (1 + bin_step / 10000) ** i.
"""

import math


def get_price_from_bin_id(bin_id: int, bin_step: int) -> float:
    """Return the price at the lower edge of a bin.

    Formula from the Meteora docs:
        price = (1 + bin_step / 10000) ** bin_id

    Args:
        bin_id: The bin index. May be negative (prices below 1.0).
        bin_step: Spacing between neighboring bins, in basis points
            (e.g. 25 means each bin's price is 0.25% above the previous).

    Returns:
        The price corresponding to bin_id. Bin 0 is always 1.0.
    """
    return (1 + bin_step / 10000) ** bin_id


def get_bin_id_from_price(price: float, bin_step: int) -> int:
    """Return the id of the bin whose price range contains `price`.

    Inverse of get_price_from_bin_id, using logarithms:
        bin_id = floor(log(price) / log(1 + bin_step / 10000))

    A price sitting strictly between two bin prices belongs to the lower
    bin, hence the floor.

    Args:
        price: Any positive price.
        bin_step: Spacing between neighboring bins, in basis points.

    Returns:
        The bin id such that price(bin_id) <= price < price(bin_id + 1).
    """
    base = 1 + bin_step / 10000
    bin_id = math.floor(math.log(price) / math.log(base))
    # The log ratio can land a hair below or above an integer due to
    # floating-point error; nudge so the containment invariant holds.
    if price >= base ** (bin_id + 1):
        bin_id += 1
    elif price < base ** bin_id:
        bin_id -= 1
    return bin_id


def get_bin_range(bin_id: int, bin_step: int) -> tuple[float, float]:
    """Return the (lower_price, upper_price) range belonging to a bin.

    lower_price is the bin's own price and upper_price is the next bin's
    price, so the range covered by bin i is [price(i), price(i + 1)).

    Args:
        bin_id: The bin index. May be negative.
        bin_step: Spacing between neighboring bins, in basis points.

    Returns:
        A (lower_price, upper_price) tuple.
    """
    return (
        get_price_from_bin_id(bin_id, bin_step),
        get_price_from_bin_id(bin_id + 1, bin_step),
    )
