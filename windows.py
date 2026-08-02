"""The market windows a run can cover, and what to call them.

Chosen from the dataset rather than picked off a calendar: the peak is the
month holding the year's highest close, the crash is the month with the
largest fall and the widest range, and the flat market is the most recent
month and also the narrowest in the year. Every figure quoted in a
description was measured off the candles.

This is a module of its own, holding nothing but the dates and their
names, so that a page can name a window without importing the machinery
that runs one. `runner` pulls in `charts` and therefore matplotlib, which
the Results page has no use for -- it is the landing page and reads
precomputed values. Naming a window is not running one.

`runner` re-exports PRESETS and DEFAULT_PRESET, so anything already
reaching for `runner.PRESETS` keeps working.
"""

from datetime import date

PRESETS = {
    "Sept 2025 peak": {
        "start": date(2025, 9, 1),
        "end": date(2025, 9, 30),
        "dates": "1-30 Sep 2025",
        "help": "The top of the year. SOL climbed from 200.47 to close at "
                "247.54 on the 18th, the highest daily close in the "
                "dataset, and touched 253.60 intraday before easing back "
                "to 208.68. Up 4.1% over the month, with a 32.9% spread "
                "between its low and its high.",
    },
    "Feb 2026 crash": {
        "start": date(2026, 2, 1),
        "end": date(2026, 2, 28),
        "dates": "1-28 Feb 2026",
        "help": "The worst month in the dataset. SOL opened at 105.24 and "
                "closed at 84.34, down 19.9%, including a fall from 104.47 "
                "to 78.23 in the three days to 5 February. It set the "
                "year's low of 67.51 and swung 57.8% between low and high.",
    },
    "Recent flat market": {
        "start": date(2026, 7, 1),
        "end": date(2026, 7, 28),
        "dates": "1-28 Jul 2026",
        "help": "The most recent month, and the quietest in the dataset: "
                "SOL started at 73.56 and finished at 73.14, a change of "
                "-0.6%, inside a 15.6% low-to-high range. The nearest "
                "thing here to a market going nowhere.",
    },
    "Full year": {
        "start": date(2025, 7, 28),
        "end": date(2026, 7, 28),
        "dates": "28 Jul 2025 - 28 Jul 2026",
        "help": "The whole dataset, and the configuration the Results page "
                "reports. SOL fell 62.1% over these twelve months, so it "
                "is one long bear market rather than a neutral sample.",
    },
}

DEFAULT_PRESET = "Full year"


def label_for(start_date, end_date) -> str:
    """The preset's name for these dates, or the dates themselves.

    A saved run keeps the dates of the candles it actually covered, not
    the name of the button that chose them, so this is how a stored row
    gets back to "Feb 2026 crash". A window nobody named still reads
    sensibly, which is what lets a hand-picked run sit in the same table
    as a preset one.
    """
    for name, preset in PRESETS.items():
        if (str(preset["start"]) == str(start_date)
                and str(preset["end"]) == str(end_date)):
            return name
    return f"{start_date} to {end_date}"
