import pandas as pd

# England bank holidays inside the calendar window (2019-11-05 -> 2020-11-04).
# Hardcoded rather than a `holidays` dependency, for reproducibility. 2020-05-08 is the VE-Day
# move of the early-May bank holiday (announced June 2019, so known to hosts at the scrape).
BANK_HOLIDAYS = pd.to_datetime([
    "2019-12-25", "2019-12-26", "2020-01-01",   # Christmas, Boxing Day, New Year's Day
    "2020-04-10", "2020-04-13",                 # Good Friday, Easter Monday
    "2020-05-08", "2020-05-25",                 # early May (moved to VE Day), Spring
    "2020-08-31",                               # Summer
])

# Festive week, both ends included; overlaps three bank holidays on purpose.
FESTIVE_START = pd.Timestamp("2019-12-24")
FESTIVE_END   = pd.Timestamp("2020-01-01")

# The extra night that turns a Monday or Friday bank holiday into a long weekend: the Sunday
# before a Monday holiday, the Thursday before a Friday one (5 nights; no festive-week holiday
# falls on a Monday or Friday in this window).
LONG_WEEKEND_NIGHTS = BANK_HOLIDAYS[BANK_HOLIDAYS.dayofweek.isin([0, 4])] - pd.Timedelta(days=1)


def timing_columns(dates: pd.Series) -> pd.DataFrame:
    """Calendar-timing design columns, one row per date, aligned on `dates.index`.

    Honesty label: every column is *derived (rule-based)* — a deterministic function of the
    calendar date alone; nothing is read from disk, nothing is estimated.

    Columns:
      is_weekend         : Friday or Saturday night (dayofweek 4 / 5, Monday = 0) — the nights
                           a weekend guest occupies.
      is_bank_holiday    : one of the 8 England bank holidays in BANK_HOLIDAYS (the holiday's
                           own night).
      festive_week       : FESTIVE_START <= date <= FESTIVE_END (2019-12-24 .. 2020-01-01, both
                           ends included). Overlaps the Dec 25 / Dec 26 / Jan 1 bank holidays on
                           purpose — separate, non-exclusive flags, so read those effects jointly.
      long_weekend_night : one of the 5 LONG_WEEKEND_NIGHTS — the night before a Monday or Friday
                           bank holiday, i.e. the extra night of a long weekend, which
                           is_bank_holiday does not mark. Used for the long-weekend robustness check.
      year_month         : a label, never a number — 13 levels (201911 .. 202011) stored as a
                           pandas category, so the window's two Novembers stay separate. The
                           regression makes the dummies via C(year_month); this function never
                           does.

    Dates are normalized to midnight before the holiday / festive tests, so a timestamp with a
    time of day still matches its calendar date.
    """
    day = dates.dt.normalize()
    return pd.DataFrame({
        "is_weekend":         dates.dt.dayofweek.isin([4, 5]),
        "is_bank_holiday":    day.isin(BANK_HOLIDAYS),
        "festive_week":       day.between(FESTIVE_START, FESTIVE_END),
        "long_weekend_night": day.isin(LONG_WEEKEND_NIGHTS),
        "year_month":         (dates.dt.year * 100 + dates.dt.month).astype("category"),
    })


if __name__ == "__main__":
    # Self-check: run `python -m src.timing`.
    # (a) Hand-picked dates, indexed by their own strings — a non-default index, so the
    #     index-alignment promise is tested too.
    days = ["2020-05-08", "2020-05-04", "2020-04-10",
            "2019-12-23", "2019-12-24", "2020-01-01", "2020-01-02",
            "2019-11-30", "2020-11-01",
            "2020-05-24", "2020-05-25"]
    test = pd.Series(pd.to_datetime(days), index=days)
    t = timing_columns(test)
    both = ["is_weekend", "is_bank_holiday"]
    assert t.index.equals(test.index)
    assert t.loc["2020-05-08", both].all()                                # Fri + VE-Day holiday
    assert not t.loc["2020-05-04", both].any()                            # Mon; holiday moved to the 8th
    assert t.loc["2020-04-10", both].all()                                # Good Friday
    assert t.loc[["2019-12-24", "2020-01-01"], "festive_week"].all()      # both ends included
    assert not t.loc[["2019-12-23", "2020-01-02"], "festive_week"].any()  # one day outside each end
    assert t.loc["2019-11-30", "year_month"] == 201911                    # the two Novembers
    assert t.loc["2020-11-01", "year_month"] == 202011                    # stay separate
    assert t.loc["2020-05-24", "long_weekend_night"]                      # Sun before Spring BH
    assert not t.loc["2020-05-25", "long_weekend_night"]                  # the holiday night itself
    assert isinstance(t["year_month"].dtype, pd.CategoricalDtype)
    # a time of day must not matter: 23:00 on 1 Jan is still the holiday and still festive
    late = timing_columns(pd.Series([pd.Timestamp("2020-01-01 23:00")]))
    assert late.loc[0, ["is_bank_holiday", "festive_week"]].all()
    # each holiday on its known weekday — catches a date typo that keeps the count at 8
    assert list(BANK_HOLIDAYS.day_name()) == ["Wednesday", "Thursday", "Wednesday", "Friday",
                                              "Monday", "Friday", "Monday", "Monday"]
    # the rule's output, spelled out: Thu before each Friday holiday, Sun before each Monday one
    assert list(LONG_WEEKEND_NIGHTS.strftime("%Y-%m-%d")) == ["2020-04-09", "2020-04-12", "2020-05-07",
                                                              "2020-05-24", "2020-08-30"]
    print("hand-picked date asserts : passed")

    # (b) Full calendar vs counts computed independently in SQL (DuckDB, 2026-09-28).
    from src.calendar_panel import load_calendar_slim

    tc = timing_columns(load_calendar_slim()["date"])
    expected = {
        "is_weekend":         8_847_072,
        "is_bank_holiday":    680_544,   # 8 dates  x 85,068 listings
        "festive_week":       765_612,   # 9 days   x 85,068 listings
        "long_weekend_night": 425_340,   # 5 nights x 85,068 listings
    }
    print(f"rows              : {len(tc):>10,}  (expected 31,050,094)")
    for col, n in expected.items():
        got = int(tc[col].sum())
        print(f"{col:<18}: {got:>10,}  (expected {n:,})")
        assert got == n
    n_levels = len(tc["year_month"].cat.categories)
    print(f"year_month levels : {n_levels:>10}  (expected 13)")
    assert len(tc) == 31_050_094 and n_levels == 13
