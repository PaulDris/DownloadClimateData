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

## Setup

1) Create/activate a Python 3.10+ environment, then install deps:

```bash
pip install -r requirements.txt
```

2) Authenticate Google Earth Engine:
- The app will prompt to authenticate on first run.
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

## Notes
- Download volume grows with more models/variables/decades. Start small to test.
- The Debug expander shows collection size for your first selection to verify data availability.
- If you see permission errors, ensure your Google account has Earth Engine access and (if using a Cloud Project) the appropriate IAM roles.

## Troubleshooting
- **Auth errors**: Run `earthengine authenticate --force` in your terminal (with venv active), then restart the app.
- **Map clicks don't update**: Ensure `streamlit-folium` is installed; refresh the page.
- **No data returned**: Check decade/scenario alignment (historical ends 2014; SSP starts 2015). Use the Debug panel to verify collection size.

