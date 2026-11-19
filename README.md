# UK Freight Sales Intelligence V4.6

Replace `app.py` and `requirements.txt` in the GitHub repository. Streamlit Community Cloud redeploys from main.

## Critical change

**All search modes now use the exact same TraderId-filtered Import and Export queries and the same fixed reporting-window end.** Previous versions mixed postcode-wide and trader-specific activity retrieval, and anchored scoring to different latest-observed months. This could generate contradictory activity scores for the same company.

The default window ends 202609, to be changed in Advanced settings when newer HMRC data is confirmed published. The application shows annual active-month counts within its rolling 24-month window (not necessarily complete calendar years).

## Coverage honesty

Territory searches are **not exhaustive** when discovery, pagination, radius, or per-trader verification caps are reached. V4.6 intentionally shows prominent warnings and exact checked counts. Each trader gets a targeted evidence query, which can be slow on large searches. No failed trader is scored as zero.

## Tests

1. Company name `Eden Horticulture Limited`: record Trader ID, import/export months, tier, window end.
2. Postcode `TF1`: locate same Trader ID and compare counts; results must match exactly when included and successfully checked.
3. Company name `Funko UK`: confirm 2026 trade and profile.
4. Postcode `CV3`: check whether Funko is present; if not, inspect directory and verification coverage diagnostics.
5. Company name `All About Food Limited`: confirm 2026 trade.
6. Postcode `M1`: inspect coverage and whether All About Food is included.

Important: HMRC published commodity-month lines are **not individual shipments**. A missing trader from a capped postcode search is not evidence of inactivity. Geographic radius remains approximate and can be incomplete.
