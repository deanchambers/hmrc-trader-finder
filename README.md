# UK Trader Finder — mobile web starter

This is a responsive Streamlit web app, intended to run on a server and open on your iPhone in Safari.

## Publish with Streamlit Community Cloud
1. Create a **private** GitHub repository (check Streamlit hosting visibility and access controls before uploading any confidential data).
2. Upload `app.py`, `requirements.txt`, and `.streamlit/config.toml` to the repository.
3. Visit https://share.streamlit.io/ and sign in with GitHub.
4. Choose **Create app**, select the repository and `app.py`, then deploy.
5. Open the resulting URL on your phone. In Safari, Share > Add to Home Screen for an app-like shortcut.

## Local run
`pip install -r requirements.txt`
`streamlit run app.py`

## Important limitations
- **Not live-tested** against HMRC from this environment. The HMRC API OData endpoint and field names must be verified after deployment.
- This version deliberately does **not** display fabricated import/export activity or A/B/C tiers. Those require an additional, tested HMRC data retrieval pipeline.
- Radius mode currently searches **only the origin postcode district**, then filters its results by straight-line distance. It is incomplete for nearby postcode districts.
- Postcode location may reflect a registered address, not a warehouse.
- The application runs on a hosting service; it does not execute Python on the phone.
- The app makes outbound requests to HMRC and postcodes.io; review organisational data policies and API usage terms.
