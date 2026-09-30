import pandas as pd

def is_active(
    listings: pd.DataFrame,
    scrape_date: str = "2019-11-05",
    review_window_months: int = 12,
    min_available_days: int = 1,
    return_components: bool = False,
    ):
    """Label each listing active (in the market) as of the scrape date.

    Active = available OR recently reviewed (the union), anchored to
    `scrape_date`, never today's date.

    Union rather than either leg alone because each signal alone misclassifies:
    availability-only marks the ~9k closed-calendar-but-recently-reviewed
    listings dead (fully booked / calendar shut between guests), while
    recency-only drops the ~11.5k available-but-never-reviewed listings
    (live supply, demand not yet proven). A listing is dormant only when
    *both* signals are dark.

    With return_components=True, returns a DataFrame exposing each leg
    (`available`, `recent_review`) alongside `active`.
    """
    available = (listings['availability_365'] >= min_available_days)
    cutoff = pd.to_datetime(scrape_date) - pd.DateOffset(months=review_window_months)
    last_review = pd.to_datetime(listings["last_review"], errors="coerce")
    recent_review = (last_review >= cutoff).fillna(False)
    active = available | recent_review
    if return_components:
        return pd.DataFrame({
            "available": available,
            "recent_review": recent_review,
            "active": active,
        })
    return active

def is_professional_host(
    listings: pd.DataFrame, 
    min_host_listings: int = 2
    ) -> pd.Series:
    """
    Label each listing as belonging to a professional (multi-listing) host.
    Calculated_host_listings_count is used because other related fields might include properties that are not in London.

    A professional host is defined as a host who has at least `min_host_listings` (default: 2) listings.
    """
    return listings["calculated_host_listings_count"] >= min_host_listings

def is_commercial_use(
    listings: pd.DataFrame,
    min_available_days: int = 90,
    ) -> pd.Series:
    """Label each listing as commercial short-let use (entire home offered beyond the 90-night cap).

    Commercial use = entire home AND availability_365 > min_available_days,
    the intersection (both must hold).

    Entire homes only, because London's 90-night annual cap on short lets
    (Deregulation Act 2015) regulates whole dwellings removed from the
    residential market — not private/shared rooms, which are home-sharing
    and exempt. The >90 threshold is the legal line itself: a whole home
    offered for more than 90 nights is set up to exceed the cap without
    change-of-use permission.

    Two caveats mean this flags capacity/intent to operate commercially,
    not a proven legal breach:
      1. Offered != let. availability_365 counts *offered* nights, not
         *booked* nights; the cap is on nights actually let (a host may
         open 200 nights but book 40).
      2. Rolling window != calendar year. The cap is per calendar year
         (resets 1 Jan), but availability_365 is the forward 365-day
         window from the scrape date (~2019-11 to ~2020-11), which spans
         two calendar years.
    """

    
    entire_home = listings["room_type"] == "Entire home/apt"
    high_availability = listings["availability_365"] > min_available_days
    return entire_home & high_availability

if __name__ == "__main__":
    # Self-check: run `python -m src.definitions` and confirm the reference
    # figures for the Nov 2019 London snapshot (n = 85,068).
    from src.data import load_listings

    listings = load_listings()
    components = is_active(listings, return_components=True)
    print(f"available leg : {int(components['available'].sum()):>6,}  (expected 56,585)")
    print(f"recency leg   : {int(components['recent_review'].sum()):>6,}  (expected 50,051)")
    print(f"active union  : {int(components['active'].sum()):>6,}  (expected 65,574)")
    print(f"professional  : {int(is_professional_host(listings).sum()):>6,}  (expected 41,533)")
    print(f"commercial    : {int(is_commercial_use(listings).sum()):>6,}  (expected 19,097)")