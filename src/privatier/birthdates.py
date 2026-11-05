"""Does a column called "birth date" really hold birth dates?

A header can be wrong, and trusting it blindly would be an assumption: a mislabelled surgery date would be
cut down to its year. So the values are checked against the rest of the file. Nothing is changed here, and
nothing is guessed: what does not fit becomes a question. Messages hold column names and counts, never values.
"""

from __future__ import annotations

import datetime as dt
from collections import Counter

_SAME_DATES = 0.9
_AGE_MISMATCH = 0.5
_AGE_TOLERANCE = 2
_MAX_AGE = 120
_MIN_VALUES = 5

DateColumn = dict[int, dt.date]  # row number -> date


def check_birth_date_column(
    birth: DateColumn,
    other_dates: dict[str, DateColumn],
    same_table: set[str],
    ages: dict[int, float],
    today: dt.date | None = None,
) -> list[str]:
    """other_dates: all other date columns of the file by label; same_table: those whose rows line up with this one."""
    today = today or dt.date.today()
    problems = []
    if len(birth) < _MIN_VALUES:
        return problems

    values = Counter(birth.values())
    identical = []
    for label, column in other_dates.items():
        shared = sum((values & Counter(column.values())).values())
        if shared / len(birth) >= _SAME_DATES:
            identical.append(label)
    if identical:
        problems.append(f"it holds the same dates as {', '.join(identical)}")

    in_future = sum(d > today for d in birth.values())
    too_old = sum((today - d).days / 365.25 > _MAX_AGE for d in birth.values())
    if in_future:
        problems.append(f"{in_future} date(s) lie in the future")
    if too_old:
        problems.append(f"{too_old} date(s) would make someone older than {_MAX_AGE}")

    for label in sorted(same_table - set(identical)):
        column = other_dates[label]
        impossible = sum(1 for row, born in birth.items() if row in column and column[row] < born)
        if impossible:
            problems.append(f"in {impossible} row(s) the birth date comes after {label}")

    if ages:
        wrong = 0
        compared = 0
        for row, born in birth.items():
            age = ages.get(row)
            if age is None:
                continue
            compared += 1
            moments = [other_dates[label][row] for label in same_table if row in other_dates[label]] or [today]
            if not any(abs((moment - born).days / 365.25 - age) <= _AGE_TOLERANCE for moment in moments):
                wrong += 1
        if compared >= _MIN_VALUES and wrong / compared >= _AGE_MISMATCH:
            problems.append(f"in {wrong} of {compared} row(s) it does not fit the age column")
    return problems
