"""Assert-based tests for bin_math. Run with: python test_bin_math.py"""

import math

from bin_math import get_price_from_bin_id, get_bin_id_from_price, get_bin_range

failures = []


def check(name, condition):
    if condition:
        print(f"PASS  {name}")
    else:
        print(f"FAIL  {name}")
        failures.append(name)


# 1. bin_id 0 always has price 1.0 for any bin step
for bin_step in (1, 5, 10, 20, 25, 50, 100, 200):
    check(f"bin 0 is 1.0 (bin_step={bin_step})",
          get_price_from_bin_id(0, bin_step) == 1.0)

# 2. bin_step 25: bin 1 is 1.0025, bin 2 is approximately 1.00500625
check("bin 1, step 25 == 1.0025",
      math.isclose(get_price_from_bin_id(1, 25), 1.0025))
check("bin 2, step 25 ~= 1.00500625",
      math.isclose(get_price_from_bin_id(2, 25), 1.00500625))

# 3. Round trip: get_bin_id_from_price(get_price_from_bin_id(i)) == i
for bin_step in (1, 10, 25, 100):
    for i in (-500, -100, -17, -1, 0, 1, 17, 100, 500):
        price = get_price_from_bin_id(i, bin_step)
        got = get_bin_id_from_price(price, bin_step)
        check(f"round trip i={i}, bin_step={bin_step}", got == i)

# 4. A price strictly between two bin prices maps to the lower bin id
for bin_step in (1, 10, 25, 100):
    for i in (-100, -3, 0, 7, 250):
        lower = get_price_from_bin_id(i, bin_step)
        upper = get_price_from_bin_id(i + 1, bin_step)
        mid = (lower + upper) / 2
        check(f"midpoint of bins {i}/{i + 1}, bin_step={bin_step} -> {i}",
              get_bin_id_from_price(mid, bin_step) == i)

# 5. get_bin_range: upper price of bin i equals price of bin i+1
for bin_step in (1, 10, 25, 100):
    for i in (-100, -1, 0, 1, 100):
        _, upper = get_bin_range(i, bin_step)
        check(f"range upper of bin {i} == price of bin {i + 1}, bin_step={bin_step}",
              upper == get_price_from_bin_id(i + 1, bin_step))

print()
if failures:
    print(f"FAIL: {len(failures)} test(s) failed:")
    for name in failures:
        print(f"  - {name}")
    raise SystemExit(1)
print("ALL TESTS PASSED")
