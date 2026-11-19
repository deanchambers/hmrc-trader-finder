# HMRC Trader Finder V4.5 — verified trade testing release

Replace `app.py` in your existing GitHub repository and commit to `main`. `requirements.txt` is unchanged.

## Tests
1. Company name: `Funko UK` (known published-trade test case; reported HMRC Trader ID 223983). Confirm the matched Trader ID and inspect import/export months, codes, and HMRC profile link.
2. Company name: `All About Food Limited` (known published-trade test case). Confirm the Trader ID, import/export activity and latest month.
3. If either test shows zero verified prospects, disable **Show verified trading prospects only** and inspect **Retrieval diagnostics**. This is an API retrieval/matching failure until independently resolved; do not interpret it as no trade.
4. Only after both company tests pass, try postcode `CV3` and `M1` and then radius.

## Important
- Published UK Trade Info commodity-month lines are **not individual shipments** and cannot determine freight spend.
- This version adds a default verified-trade-only view, source links, and diagnostics; it does **not** solve the existing district-wide activity pagination/coverage limitation.
- Trader candidate caps and incomplete radius postcode discovery can omit genuine traders. Do not use as an exhaustive territory list or production rollout yet.
- Data sources are public HMRC UK Trade Info API and postcodes.io.
