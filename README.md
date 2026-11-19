# HMRC Freight Sales Intelligence V4.3 — stability update

Replace `app.py` in GitHub. `requirements.txt` remains unchanged.

Fixes: dark-mode metric contrast; stable CSV schema when activity is unavailable; fallback for zero-result district queries; advanced activity safety limit; diagnostics; explicit partial-radius warnings.

**Not production-certified.** Live HMRC API endpoints, pagination completeness, postcode district matching, publication coverage, activity-to-trader joins, and geospatial coverage still require independent end-to-end validation. HMRC commodity-month lines are not shipments. Radius discovery is sampled if trader caps or outcode limits are reached.

Test: Funko, TF2, TF, WS10, CV3 4PW radius. Compare Trader IDs and activity with HMRC source. Review diagnostics.
