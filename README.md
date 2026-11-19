# UK Freight Sales Intelligence V4.2

Three search modes: company name (HMRC CompanyName), postcode area/district, and approximate multi-district postcode radius.

## Important
- Radius search uses nearby postcode district centroids as candidates, then geocodes individual trader postcodes to filter by distance. It can miss traders in districts whose centroids lie outside the candidate radius or if API limits are hit.
- Company-name search matches published HMRC names, not necessarily trading brands; try a shorter distinctive substring.
- Trader and activity caps can cause incomplete results; the app reports warnings and withholds scores when activity is capped.
- 12/24-month activity counts are commodity-month evidence, not shipment counts or freight spend.
- Live integration must be tested after deployment.

Upload app.py to GitHub main and retain requirements.txt.
