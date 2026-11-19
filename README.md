# HMRC Freight Sales Intelligence — v3

Replace your GitHub repository's `app.py` and `requirements.txt` with these files. Streamlit Cloud will automatically redeploy.

## Features
- HMRC trader search by postcode area/district
- Import and export activity over 12 complete calendar months
- Direction, observed months, first/last month, published commodity-month lines, commodity IDs
- A/B/C tiers and heuristic sales priority, reason to contact
- Filters and CSV export ready for a separate approved enrichment agent

## Caveats
- Live HMRC Import/Export endpoint filters are **not verified end-to-end** from this environment. Check Streamlit logs if they fail.
- Published commodity-month records are **not shipment counts** and do not give freight values.
- The app queries the latest 12 *complete calendar* months; HMRC publication can lag, making recency appear older than it is. A future version should use latest *published* month.
- Activity caps: if either direction hits the cap, the app withholds scoring. Trader cap means company results may be partial.
- Radius mode only covers the origin postcode district; it is NOT complete radius coverage.
- Commodity filtering currently works on commodity IDs, not descriptions. Verify ID mapping before excluding regulated goods.
- Registered address may not be the operating site.
- Review organisation policy before sending prospect data to external AI services.

## Quick validation
Search WS10 with a low maximum trader count. Confirm columns show 'Trade direction', 'Import active months (12m)', 'Export active months (12m)', 'Latest import (12m)', 'Latest export (12m)', 'Priority', 'Why contact'. If not, check the app's error message/logs.
