import pandas as pd
from src.calendar_panel import load_calendar_slim

def listing_price_features(cal=None, available_only=False):
    """One row per listing: posted-price behavior features from the slim calendar panel.

    Honesty label: every feature is *derived (rule-based)* — a deterministic transform
    of observed daily posted prices, no fitted model, no assumed parameters.

    No-revision caveat: these measure cross-date variation in one posted surface,
    not update frequency. A single Nov-2019 snapshot shows the price posted for each
    forward date; it cannot show how often a host revised a price. Never read
    cross_date_change_rate as an update/lead-time rate.

    Features (all within-listing):
      n_days, n_price_values      : calendar-day count; distinct posted prices.
      varying                     : n_price_values > 1.
      rel_range, cv               : (max-min)/mean; std/mean — dispersion of the surface.
      round_share, round10_share  : share of days at £5- / £10-multiples.
      cross_date_change_rate      : share of consecutive-day pairs with a different price.
      weekend_premium_raw         : mean Fri/Sat-night price / mean other-night price
                                    (weekend = Friday & Saturday nights). NaN if a listing
                                    lacks either group; not filled.
      monthly_amplitude           : max / min of the ~13 within-listing monthly means,
                                    incl. partial edge months (Nov'19 ~26d, Nov'20 ~4d) —
                                    those two means are thinner by construction.

    available_only : if True, filter to available==True before all features. ~33% of
        listings have zero available days and drop out entirely; "consecutive" days in
        cross_date_change_rate then span consecutive *available* days, skipping blocks.
    """
    if cal is None:
        cal = load_calendar_slim()
    if available_only:
        cal = cal[cal["available"]]

    n_days = cal.groupby("listing_id").size() 
    priced = cal.dropna(subset=["price"])
    priced = priced.assign(
        is_round5  = priced["price"] % 5  == 0,
        is_round10 = priced["price"] % 10 == 0,
    )

    agg = priced.groupby("listing_id").agg(
        pmin           = ("price", "min"),
        pmax           = ("price", "max"),
        pmean          = ("price", "mean"),
        pstd           = ("price", "std"),
        n_price_values = ("price", "nunique"),
        round_share    = ("is_round5", "mean"),
        round10_share  = ("is_round10", "mean"),
    )
    rel_range = (agg["pmax"] - agg["pmin"]) / agg["pmean"]
    cv        = agg["pstd"] / agg["pmean"]
    varying   = agg["n_price_values"] > 1

    ps  = priced.sort_values(["listing_id", "date"])
    lid = ps["listing_id"]
    p   = ps["price"]
    changed = p.ne(p.shift()) & lid.eq(lid.shift())
    grp = changed.groupby(lid)
    cross_date_change_rate = grp.sum() / (grp.size() - 1)

    assert cross_date_change_rate.dropna().between(0, 1).all(), "change rate out of [0,1]"

    is_weekend = priced["date"].dt.dayofweek.isin([4, 5]).rename("is_weekend")
    wk = priced.groupby(["listing_id", is_weekend])["price"].mean().unstack()
    weekend_premium_raw = wk[True] / wk[False]

    month = priced["date"].dt.to_period("M").rename("month")
    mm = priced.groupby(["listing_id", month])["price"].mean()
    by = mm.groupby(level="listing_id")
    monthly_amplitude = by.max() / by.min()
    
    features = pd.DataFrame({
            "n_days":          n_days,
            "n_price_values":  agg["n_price_values"],
            "varying":         varying,
            "rel_range":       rel_range,
            "cv":              cv,
            "round_share":     agg["round_share"],
            "round10_share":   agg["round10_share"],
            "cross_date_change_rate": cross_date_change_rate,
            "weekend_premium_raw": weekend_premium_raw,
            "monthly_amplitude": monthly_amplitude
        })
    return features 

def dynamism_index(features):
    """Continuous dynamism index — a listing's average percentile position in price movement.

    Honesty label: *derived (rule-based)* — a printed formula over named observed
    features, NOT a fitted model. Equal 1/3 weights by fiat, stated here.

    Formula (per listing):
        index = features[cols].rank(pct=True).mean(axis=1)
        cols  = cross_date_change_rate, n_price_values, rel_range
                (frequency / granularity / amplitude of the posted-price surface)

    Ranks, not raw or winsorized values: percentile ranks are scale-free, so a single
    raw-feature outlier (e.g. the weekend-premium listing at 100.68, or the long right
    tails of n_price_values / rel_range) is capped at rank 1.0 — it can sit at the top but
    cannot stretch the scale or dominate the index. This is also the fewest-knobs choice:
    no clip point and no per-feature normalization to assume.

    Cohort-relative by construction: the index ranks *within the population passed in*.
    Pass the active-listing feature frame for the primary typology; pass the available-only
    or full-85,068 frame for the robustness variants — each re-ranks within its own
    population, so index values are not comparable across populations.

    Read it honestly — the three components are highly collinear (Spearman 0.83-0.90 on the
    active population): the index is essentially ONE latent "price-movement" dimension
    measured three ways, not three orthogonal axes. Averaging three features buys
    reliability / robustness (no single feature or its outliers drives the ordering), NOT
    independent information. Never describe it as capturing three distinct dimensions.

    Validators kept OUT of the index on purpose: weekend_premium_raw, monthly_amplitude and
    round_share are excluded, so the downstream checks — "fluid listings carry the weekend
    premium" and "fluid listings are less round-numbered" — stay outside the index (the
    weekend check only partly: weekly Fri/Sat pricing raises the change rate).

    No-revision caveat (inherited): the components measure cross-date variation in one
    posted-price surface, not update frequency; the index is a texture score, never a
    dynamic-updating or lead-time rate.

    features : one row per listing (listing_price_features output), already restricted to
        the ranking population; must carry the three component columns with no NaN (asserted).
    returns : Series in [0, 1] indexed by listing_id, aligned to features.index.
    """
    cols = ["cross_date_change_rate", "n_price_values", "rel_range"]
    assert features[cols].notna().all().all()
    ranks = features[cols].rank(pct=True)    
    return ranks.mean(axis=1)

def classify_texture(features, fluid_quantile=0.80):
    """Three-way pricing-texture typology: flat / sticky / fluid, one label per listing.

    Honesty label: *derived (rule-based)* — a printed threshold rule over the dynamism
    index, NOT a fitted model or a cluster assignment. Exhaustive and mutually exclusive:
    every listing gets exactly one label and the three shares sum to the population.

    Buckets (computed on whatever population `features` holds — primary = active, 65,574):
        flat   : not varying (n_price_values == 1, equivalently cross_date_change_rate == 0)
                 — the price never differs across calendar dates.
        fluid  : varying AND dynamism_index >= index.quantile(fluid_quantile)
                 — the most dynamic tail (default top quintile).
        sticky : varying but below the fluid cut — the residual middle.

    Threshold = a STATED CONVENTION, not a discovered boundary. The varying index
    distribution has no natural break (smooth ECDF), so `fluid_quantile` is a chosen cut:
    0.80 = "the most dynamic fifth." It is deliberately a round quintile, NOT reverse-
    engineered to any target share — the fluid share is therefore definitional; the
    findings live in the validations (features outside the index), not in the share itself. The quantile
    is taken over the whole passed population; flats sit at the bottom of the index, far
    below the cut, so they never fall into the fluid band.

    Cohort-relative (inherited from dynamism_index): re-ranks within the passed frame, so
    the same function serves the robustness variants (available-only, full 85,068) by
    re-applying the rule within each population.

    Validation (active population; features kept OUT of the index; the weekend check only partly
    independent, since weekly Fri/Sat pricing raises the change rate), all
    monotone flat -> sticky -> fluid: round_share median 1.000 / 0.907 / 0.400 (fluid least
    round-numbered); weekend_premium_raw median 1.0000 / 1.0005 / 1.0358 (fluid carries the
    weekend premium); professional ratio P(fluid|prof)/P(fluid|casual) = 2.38x (robust
    2.22-2.46x across fluid_quantile 0.75-0.85).

    Framing (state verbatim wherever the typology is reported): the typology is "consistent
    with hand-set vs algorithmic pricing; tool adoption is unobserved — this is a typology,
    not a Smart Pricing detector."

    features : one row per listing (listing_price_features output), already restricted to the
        ranking population; must carry `varying` and the three index components (no NaN).
    fluid_quantile : the stated convention (default 0.80); the index quantile at/above which a
        varying listing is labelled fluid.
    returns : Series of {"flat","sticky","fluid"}, indexed by listing_id, aligned to features.index.
    """
    idx = dynamism_index(features)
    fluid_cut = idx.quantile(fluid_quantile)
    texture = pd.Series("sticky", index=features.index)
    texture[~features["varying"]] = "flat"
    texture[features["varying"] & (idx >= fluid_cut)] = "fluid"
    return texture

if __name__ == "__main__":
    f      = listing_price_features()
    f_avail = listing_price_features(available_only=True)
    share = f["varying"].mean()
    print(f"listings (all days)      : {len(f):>7,}  (expected 85,068)")
    print(f"listings (available only): {len(f_avail):>7,}  ({len(f_avail)/len(f):.1%} of all)")
    print(f"any variation      : {share:>7.3%}  (expected 56.6%)")
    print(f"flat complement    : {1 - share:>7.3%}  (expected 43.4%)")
    med = f.loc[f["varying"], "rel_range"].median()
    print(f"median rel_range   : {med:>7.3%}  (expected 32.5%)")
    print(f"change rate  [min,max] : [{f['cross_date_change_rate'].min():.3f}, {f['cross_date_change_rate'].max():.3f}]  (expect within [0,1])")
    print(f"change rate  median    : {f['cross_date_change_rate'].median():.3%}")
    print(f"weekend prem median    : {f['weekend_premium_raw'].median():.4f}  (expect just above 1.0)")
    print(f"weekend prem NaNs      : {f['weekend_premium_raw'].isna().sum()}  (expect ~0)")
    print(f"monthly amp  median    : {f['monthly_amplitude'].median():.4f}")
    print(f"monthly amp  min       : {f['monthly_amplitude'].min():.4f}  (expect 1.0)")
    pd.testing.assert_frame_equal(f, listing_price_features())
    assert f["cross_date_change_rate"].between(0, 1).all()
    assert (f["monthly_amplitude"] >= 1).all()
     # --- typology self-check (active population) ---
    from src.data import load_listings
    from src.definitions import is_active, is_professional_host

    listings = load_listings()
    active_ids = listings.loc[is_active(listings), "id"]
    fa = f.loc[f.index.isin(active_ids)].copy()
    fa["professional"] = is_professional_host(listings.set_index("id")).reindex(fa.index)
    fa["texture"] = classify_texture(fa)

    order = ["flat", "sticky", "fluid"]
    shares = fa["texture"].value_counts(normalize=True).reindex(order)
    rs = fa.groupby("texture")["round_share"].median().reindex(order)
    wp = fa.groupby("texture")["weekend_premium_raw"].median().reindex(order)
    prof = fa["professional"]
    ratio = (fa.loc[prof, "texture"] == "fluid").mean() / (fa.loc[~prof, "texture"] == "fluid").mean()

    print(f"\nactive listings    : {len(fa):>7,}  (expected 65,574)")
    print(f"texture shares     : {shares['flat']:.1%} / {shares['sticky']:.1%} / {shares['fluid']:.1%}  (expect 34.9 / 45.1 / 20.0)")
    print(f"round_share median : {rs['flat']:.3f} / {rs['sticky']:.3f} / {rs['fluid']:.3f}  (expect down; fluid ~0.400)")
    print(f"wknd prem median   : {wp['flat']:.4f} / {wp['sticky']:.4f} / {wp['fluid']:.4f}  (expect up; fluid ~1.0358)")
    print(f"prof fluid ratio   : {ratio:.2f}x  (expected 2.38x)")

    assert set(fa["texture"].unique()) == set(order),      "texture labels off"
    assert rs["flat"] >= rs["sticky"] >= rs["fluid"],      "round_share not monotone"
    assert wp["fluid"] > wp["flat"],                        "fluid should carry weekend premium"

