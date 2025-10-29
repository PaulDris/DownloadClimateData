# Earth Engine Climate Downloader (NASA/GDDP-CMIP6)

A simple Streamlit app to download daily climate change time series from Google Earth Engine's **NASA/GDDP-CMIP6** dataset for any clicked location.

## Features
- Click a location on the map or enter coordinates
- Select decades, variables (bands), models (multi-select), and scenarios (multi-select)
- Download combined CSV to your local machine

## Dataset Structure
- **NASA/GDDP-CMIP6** (correct ID)
- Each image has 9 bands (all variables together): `tas`, `tasmax`, `tasmin`, `pr`, `hurs`, `huss`, `rsds`, `rlds`, `sfcWind`
- Properties: `model`, `scenario`, `year`, `month`, `day`
- Historical: 1950–2014; Scenarios (SSP): 2015–2100

## Setup (local development)

1) Create/activate a Python 3.10+ environment, then install deps:

```bash
pip install -r requirements.txt
```

2) Authenticate Google Earth Engine (OAuth):
    - The app will attempt to use your existing credentials; if missing, it may prompt for OAuth in the browser.
    - Or run manually in your terminal:
       ```bash
       earthengine authenticate
       ```

## Run

```bash
streamlit run app.py
```

Open the URL shown (typically http://localhost:8501).

## Usage

1. **Earth Engine setup**: 
   - Leave Cloud Project **empty** for personal accounts.
   - Or enter your organization's Cloud Project ID if required.
   - Click "Apply & Init EE" and verify "Dataset reachable!"

2. **Location**: Click the map or type `lat,lon` (e.g., `51.5074,-0.1278`)

3. **Decades**: Select one or more decades. 
   - Historical: 1950s–2010s (up to 2014)
   - Scenarios: 2020s–2090s (2015–2100)

4. **Variables (bands)**: Pick from 9 available bands:
   - `tasmax`, `tasmin`, `tas` (temperatures in K, converted to °C)
   - `pr` (precipitation in kg m-2 s-1, converted to mm/day)
   - `hurs`, `huss` (humidity)
   - `rsds`, `rlds` (radiation)
   - `sfcWind` (wind speed)

5. **Models**: Multi-select from ~30 CMIP6 models (discovered dynamically)

6. **Scenarios**: Multi-select from `historical`, `ssp126`, `ssp245`, `ssp370`, `ssp585`

7. Click **"Fetch & Prepare CSV"** and download the results.

## Deploying on Streamlit Cloud (service account)

Interactive OAuth isn’t available on Streamlit Cloud. Use a Google Cloud service account instead:

1) In Google Cloud Console
   - Create or use an existing project (note this ID; e.g., `my-ee-project`).
   - Enable the Earth Engine API for the project.
   - Create a Service Account and generate a JSON key.

2) Give the Service Account Earth Engine access
   - Visit https://code.earthengine.google.com/serviceaccount
   - Add the service account email. Share any required EE assets with it if needed.

3) Add Streamlit Secrets for the app
   - In Streamlit Cloud → Your app → Settings → Secrets, add:

     ```toml
     EE_PROJECT = "my-ee-project"

     # Option A: Paste the full service account key JSON as a table
     [gcp_service_account]
     type = "service_account"
     project_id = "my-ee-project"
     private_key_id = "..."
     private_key = "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
     client_email = "my-sa@my-ee-project.iam.gserviceaccount.com"
     client_id = "..."
     token_uri = "https://oauth2.googleapis.com/token"
     auth_uri = "https://accounts.google.com/o/oauth2/auth"
     auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
     client_x509_cert_url = "https://www.googleapis.com/robot/v1/metadata/x509/my-sa%40my-ee-project.iam.gserviceaccount.com"
     universe_domain = "googleapis.com"

     # Option B: Alternatively, provide explicit keys
     # EE_SERVICE_ACCOUNT = "my-sa@my-ee-project.iam.gserviceaccount.com"
     # EE_PRIVATE_KEY_JSON = "{\"type\":\"service_account\",...}"
     ```

The app now initializes Earth Engine using the service account in production, but still supports OAuth locally.

## Notes
- Download volume grows with more models/variables/decades. Start small to test.
- The Debug expander shows collection size for your first selection to verify data availability.
- If you see permission errors, ensure your Google account has Earth Engine access and (if using a Cloud Project) the appropriate IAM roles.

## Troubleshooting
- **Auth errors (local)**: Run `earthengine authenticate --force` in your terminal (with venv active), then restart the app.
- **Auth errors (Streamlit Cloud)**: Ensure `EE_PROJECT` and a valid service account JSON are in Secrets, and the service account has Earth Engine access.
- **Map clicks don't update**: Ensure `streamlit-folium` is installed; refresh the page.
- **No data returned**: Check decade/scenario alignment (historical ends 2014; SSP starts 2015). Use the Debug panel to verify collection size.

