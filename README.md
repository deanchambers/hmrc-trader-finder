# UK Freight Sales Intelligence V4

This app queries HMRC UK Trade Info directly; **no spreadsheet upload is needed**.

## Install / deployment
Replace `app.py` and `requirements.txt` in the root of your GitHub repository. Commit to `main`; Streamlit Community Cloud should redeploy the existing app. The ZIP contains both files and this README.

## Features
- Postcode area and district trader search with HMRC pagination and configurable limits
- Latest 12 vs 24 months of **published commodity-month activity** for imports and exports
- 30-calendar-month retrieval window to accommodate reporting lag; window anchored to latest month observed in the selected territory, NOT necessarily the UK's official latest published month
- Separate import/export active months, record lines, latest/first observation, commodity codes, indicative HS chapter groups
- Activity tiers A/B/C, recent activity, trend (12 months versus preceding 12), and transparent heuristic sales priority
- Sales shortlist, analytical table, and two CSV exports for enrichment
- Commodity review flags; no invented shipment quantities, trade values, or contacts
- Partial results and activity-cap warnings

## Critical limitations
- **Not yet verified end-to-end against HMRC's live API from this environment.** Validate a known trader and both activity flows before sales use.
- The 24-month denominator is a calendar window. Missing published months, low territory activity or publication lag may bias scores. The displayed observed-month count is a territory-level indicator, not a publication certificate.
- Radius mode searches only the origin postcode district and is **NOT a complete radius search**. Do not treat it as a full territory sweep.
- HMRC's trade records are commodity-month appearances, not shipments, tonnage, freight spend, country of origin/destination, or proof of freight mode.
- Registered addresses may not be logistics sites; indicative HS chapter groups are broad, not definitive hazardous-cargo classifications.
- CRM ownership, business websites, and decision-maker contacts require approved external integrations. None are invented.
- API pagination and result caps can make a search partial. Use narrow districts for complete retrieval and verify the output.
- Do not upload company-confidential information to an unapproved AI platform.

## Recommended test
Search WS10 with max 500 traders and 30,000 activity records per flow. Check data window end, compare two known companies against HMRC UK Trade Info's trader search, and inspect both exports. If the API errors, open Streamlit Manage app > Logs.

API documentation: https://www.uktradeinfo.com/api-documentation/
