import os
import io
import json
from datetime import datetime
from typing import List, Tuple, Dict

import streamlit as st
import pandas as pd

# Optional mapping widgets
try:
    from streamlit_folium import st_folium
    import folium
except Exception:
    st.write("Installing map dependencies is recommended: streamlit-folium, folium")

# Earth Engine imports
try:
    import ee
except Exception as e:
    ee = None
    st.error("Google Earth Engine Python API not installed. Please install earthengine-api.")

APP_TITLE = "Earth Engine Climate Downloader (NEX-GDDP-CMIP6)"
EE_PROJECT_ENV = os.getenv("EE_PROJECT", "")

# Known fallbacks for models, variables, scenarios if dynamic fetch fails
KNOWN_VARIABLES = [
    # Daily variables in NASA/NEX-GDDP-CMIP6
    "tasmin",  # Daily minimum near-surface air temperature (K)
    "tasmax",  # Daily maximum near-surface air temperature (K)
    "pr",      # Daily precipitation (kg m-2 s-1) -> convert to mm/day
    "hurs",    # Daily mean near-surface relative humidity (%)
    "rsds",    # Daily mean surface downwelling shortwave radiation (W/m^2)
    "sfcWind"  # Daily mean near-surface wind speed (m/s)
]

KNOWN_SCENARIOS = [
    "historical",  # 1950-2014 in NEX-GDDP-CMIP6
    "ssp126",
    "ssp245",
    "ssp370",
    "ssp585",
]

KNOWN_MODELS = [
    # Common subset; dynamic listing will replace this when possible
    "ACCESS-CM2", "ACCESS-ESM1-5", "BCC-CSM2-MR", "CNRM-CM6-1", "CNRM-ESM2-1",
    "CanESM5", "EC-Earth3", "EC-Earth3-Veg", "FGOALS-g3", "GFDL-ESM4",
    "GISS-E2-1-G", "INM-CM4-8", "INM-CM5-0", "IPSL-CM6A-LR", "KIOST-ESM",
    "MIROC6", "MPI-ESM1-2-HR", "MPI-ESM1-2-LR", "MRI-ESM2-0", "NorESM2-LM",
    "NorESM2-MM", "UKESM1-0-LL"
]

UNITS_HINT = {
    "tasmin": "K (Kelvin)",
    "tasmax": "K (Kelvin)",
    "pr": "kg m-2 s-1 (≈ mm/s); multiply by 86400 for mm/day",
    "hurs": "percent",
    "rsds": "W/m^2",
    "sfcWind": "m/s",
}

DECADES = {
    # Allow 1950s–2090s; actual availability depends on scenario/historical
    f"{y}s ({y}-01-01 to {y+9}-12-31)": (f"{y}-01-01", f"{y+9}-12-31")
    for y in range(1950, 2100, 10)
}

# Correct Earth Engine dataset ID for CMIP6 downscaled data
COLL_ID = "NASA/GDDP-CMIP6"

# Will be filled dynamically after EE init and first metadata probe
PROP_KEYS_DEFAULT = {
    "model": "model",
    "scenario": "experiment_id",  # CMIP6 commonly uses experiment_id
    "variable": "variable_id",
}

def _init_ee(project: str | None = None) -> Tuple[bool, str]:
    if ee is None:
        return False, "ee not installed"
    try:
        # Try to initialize; if not authenticated, prompt user
        # Only pass project if explicitly provided (non-empty)
        if project and project.strip():
            ee.Initialize(project=project.strip())
        else:
            ee.Initialize()
        return True, "initialized"
    except Exception:
        # Try interactive auth if possible
        try:
            ee.Authenticate()
            if project and project.strip():
                ee.Initialize(project=project.strip())
            else:
                ee.Initialize()
            return True, "authenticated"
        except Exception as e:
            return False, str(e)

def _detect_property_keys() -> Dict[str, str]:
    """Detect property names for model/scenario/variable on NASA/GDDP-CMIP6."""
    if ee is None:
        return PROP_KEYS_DEFAULT
    try:
        img = ee.ImageCollection(COLL_ID).limit(1).first()
        names = set(img.propertyNames().getInfo())
        candidates = {
            "model": ["model", "GCM", "gcm", "Model"],
            "scenario": ["scenario", "experiment", "experiment_id"],
            "variable": ["variable", "variable_id"],
        }
        picked = {}
        for k, opts in candidates.items():
            found = next((n for n in opts if n in names), None)
            if not found:
                found = PROP_KEYS_DEFAULT.get(k, opts[0])
            picked[k] = found
        return picked
    except Exception:
        return PROP_KEYS_DEFAULT


def list_dynamic_options() -> Tuple[List[str], List[str], List[str]]:
    """Return (models, variables, scenarios) from the collection properties if possible."""
    if ee is None:
        return KNOWN_MODELS, KNOWN_VARIABLES, KNOWN_SCENARIOS
    try:
        coll = ee.ImageCollection(COLL_ID)
        keys = st.session_state.get("prop_keys") or _detect_property_keys()
        st.session_state["prop_keys"] = keys
        models = coll.aggregate_array(keys['model']).distinct().getInfo()
        variables = coll.aggregate_array(keys['variable']).distinct().getInfo()
        scenarios = coll.aggregate_array(keys['scenario']).distinct().getInfo()
        # Sort for UX
        return sorted(set(models)), sorted(set(variables)), sorted(set(scenarios))
    except Exception:
        return KNOWN_MODELS, KNOWN_VARIABLES, KNOWN_SCENARIOS


def ui_sidebar():
    st.title(APP_TITLE)
    # EE setup panel
    with st.expander("Earth Engine setup and status", expanded=False):
        st.markdown("""
**Important:** If you see permission errors for a project number (e.g., 517222506229):
1. Leave the Cloud Project field **empty** to use your default EE account, OR
2. Enter your actual Cloud Project ID (e.g., `axial-edition-469618-t6`) if required by your organization.
3. Visit [Google Cloud IAM](https://console.cloud.google.com/iam-admin/iam) for the project and grant yourself `roles/serviceusage.serviceUsageConsumer` or use a personal Earth Engine account (no project needed).
        """)
        ee_proj = st.text_input("EE Cloud Project (optional; leave empty for default)", value=st.session_state.get("ee_project", ""))
        colA, colB = st.columns(2)
        with colA:
            if st.button("Apply project & Init EE"):
                st.session_state["ee_project"] = ee_proj.strip()
                proj_to_use = st.session_state["ee_project"] if st.session_state["ee_project"] else None
                ok, msg = _init_ee(project=proj_to_use)
                st.write(f"Init: {ok}, msg: {msg}")
                # Quick collection check
                if ok and ee is not None:
                    try:
                        n = ee.ImageCollection(COLL_ID).limit(1).size().getInfo()
                        st.write(f"Dataset reachable ✓ (example size limit: {n})")
                    except Exception as e:
                        st.warning(f"Dataset check failed: {e}")
        with colB:
            st.caption("Tip: If initialization fails, run 'earthengine authenticate --force' in your virtualenv, then return here and click Apply again.")

    proj_to_use = st.session_state.get("ee_project", "").strip() if st.session_state.get("ee_project") else None
    ok, msg = _init_ee(project=proj_to_use)
    if not ok:
        st.warning("Earth Engine not initialized. Click the button below to authenticate.")
        if st.button("Authenticate with Earth Engine"):
            proj_to_use_auth = st.session_state.get("ee_project", "").strip() if st.session_state.get("ee_project") else None
            _ = _init_ee(project=proj_to_use_auth)
            st.rerun()
        st.stop()

    st.markdown("Download daily CMIP6 downscaled climate data for a clicked location and decades.")

    models, variables, scenarios = list_dynamic_options()

    # Location: text input + map click
    st.subheader("1) Location")
    coords = st.text_input("Enter lat,lon", "51.5074,-0.1278")
    try:
        lat0, lon0 = [float(v.strip()) for v in coords.split(",")]
    except Exception:
        lat0, lon0 = 51.5074, -0.1278

    st.caption("Tip: Click on the map to update the coordinates.")
    m = folium.Map(location=[lat0, lon0], zoom_start=3, control_scale=True)
    folium.Marker([lat0, lon0], tooltip="Selected Point").add_to(m)
    map_state = st_folium(m, height=350, width=None, returned_objects=["last_clicked"])
    if map_state and map_state.get("last_clicked"):
        lat0 = map_state["last_clicked"]["lat"]
        lon0 = map_state["last_clicked"]["lng"]
        st.session_state["coords"] = f"{lat0:.5f},{lon0:.5f}"
        st.rerun()

    if "coords" in st.session_state:
        st.write("Selected:", st.session_state["coords"])
        coords = st.session_state["coords"]

    st.subheader("2) Time periods")
    decades = st.multiselect("Choose decades (multi-select)", list(DECADES.keys()), default=[
        "2010s (2010-01-01 to 2019-12-31)",
        "2020s (2020-01-01 to 2029-12-31)",
    ])

    st.subheader("3) Variables")
    # Ensure defaults exist in discovered variables
    default_vars = [v for v in ["tasmax", "tasmin", "pr"] if v in variables] or variables[:3]
    sel_vars = st.multiselect("Variables (NEX-GDDP-CMIP6)", variables, default=default_vars) 
    with st.expander("Units and notes"):
        for v in sel_vars:
            st.write(f"- {v}: {UNITS_HINT.get(v, '')}")

    st.subheader("4) Models")
    sel_models = st.multiselect("Models (multi-select)", models, default=models[:5])

    st.subheader("5) Scenarios")
    # Prefer showing historical + one SSP if available
    default_scen = [s for s in ["historical", "ssp245", "ssp585"] if s in scenarios] or scenarios[:2]
    sel_scen = st.multiselect("Scenarios (multi-select)", scenarios, default=default_scen) 

    st.divider()
    # Quick debug: show count for the first selection to help diagnose "no data"
    with st.expander("Debug: check first selection size", expanded=False):
        try:
            keys = st.session_state.get("prop_keys") or _detect_property_keys()
            st.write(f"Detected property keys: {keys}")
            if models and scenarios and variables and decades:
                (s0, e0) = DECADES[decades[0]]
                c = (ee.ImageCollection(COLL_ID)
                     .filter(ee.Filter.eq(keys['model'], models[0]))
                     .filter(ee.Filter.eq(keys['scenario'], scenarios[0]))
                     .filter(ee.Filter.eq(keys['variable'], variables[0]))
                     .filterDate(s0, e0))
                st.write("Example collection size:", c.size().getInfo())
        except Exception as e:
            st.write("Debug check failed:", e)

    run = st.button("Fetch & Prepare CSV")
    return run, (coords, decades, sel_vars, sel_models, sel_scen)


def clamp_dates_for_scenario(start_date: str, end_date: str, scenario: str) -> Tuple[str, str]:
    # NEX-GDDP-CMIP6 generally: historical 1950-01-01..2014-12-31; SSP 2015-01-01..2100-12-31
    sdt = pd.to_datetime(start_date)
    edt = pd.to_datetime(end_date)
    if scenario == "historical":
        s_min, s_max = pd.Timestamp("1950-01-01"), pd.Timestamp("2014-12-31")
    else:
        s_min, s_max = pd.Timestamp("2015-01-01"), pd.Timestamp("2100-12-31")
    sdt = max(sdt, s_min)
    edt = min(edt, s_max)
    if sdt > edt:
        return None, None
    return sdt.strftime("%Y-%m-%d"), edt.strftime("%Y-%m-%d")


def fetch_point_timeseries(lat: float, lon: float, start: str, end: str,
                           variable: str, model: str, scenario: str,
                           scale: int = 10000) -> pd.DataFrame:
    """Fetch daily time series for a point using getRegion. Returns columns: date,value,variable,model,scenario."""
    point = ee.Geometry.Point([lon, lat])
    coll = ee.ImageCollection(COLL_ID) 
    # Filter by variable/model/scenario and date
    keys = st.session_state.get("prop_keys") or _detect_property_keys()
    coll = (coll
        .filter(ee.Filter.eq(keys['variable'], variable))
        .filter(ee.Filter.eq(keys['model'], model))
        .filter(ee.Filter.eq(keys['scenario'], scenario))
        .filterDate(start, end)
       )
    # Each image represents a day; select the band. In NEX-GDDP-CMIP6, band name usually equals variable.
    coll = coll.select(variable)
    # getRegion returns rows: [time, latitude, longitude, variable]
    try:
        arr = coll.getRegion(point, scale).getInfo()
    except Exception as e:
        # Return empty DF with expected columns
        return pd.DataFrame(columns=["date","value","variable","model","scenario"]) 

    # Convert to DataFrame
    if not arr or len(arr) < 2:
        return pd.DataFrame(columns=["date","value","variable","model","scenario"]) 
    header, rows = arr[0], arr[1:]
    # time may be "time" in ms or "date"; try both
    time_idx = header.index('time') if 'time' in header else (header.index('date') if 'date' in header else None)
    band_idx = header.index(variable) if variable in header else None
    if time_idx is None or band_idx is None:
        return pd.DataFrame(columns=["date","value","variable","model","scenario"]) 
    recs = []
    for r in rows:
        try:
            t = pd.to_datetime(r[time_idx], unit='ms', utc=True).tz_convert(None)
        except Exception:
            try:
                t = pd.to_datetime(r[time_idx])
            except Exception:
                continue
        val = r[band_idx]
        recs.append({
            "date": t.date().isoformat(),
            "value": val,
            "variable": variable,
            "model": model,
            "scenario": scenario
        })
    df = pd.DataFrame.from_records(recs)
    # Helpful conversions
    if variable == 'pr' and not df.empty:
        # kg m-2 s-1 → mm/day (1 kg m-2 = 1 mm water layer; multiply by seconds per day)
        df['value'] = df['value'].astype(float) * 86400.0
    if variable in ('tasmax','tasmin') and not df.empty:
        # Kelvin → Celsius
        df['value'] = df['value'].astype(float) - 273.15
    return df


def main():
    run, (coords, decades, sel_vars, sel_models, sel_scen) = ui_sidebar()
    if not run:
        return

    try:
        lat, lon = [float(v.strip()) for v in coords.split(",")]
    except Exception:
        st.error("Invalid coordinates. Use 'lat,lon'.")
        return

    # Build list of date ranges from decades
    date_ranges = [DECADES[d] for d in decades]

    st.info("Fetching data... This can take a while for many combinations.")

    all_frames = []
    for scenario in sel_scen:
        for (start, end) in date_ranges:
            s_adj, e_adj = clamp_dates_for_scenario(start, end, scenario)
            if not s_adj:
                continue
            for model in sel_models:
                for var in sel_vars:
                    with st.spinner(f"{scenario} {model} {var} {s_adj}..{e_adj}"):
                        df = fetch_point_timeseries(lat, lon, s_adj, e_adj, var, model, scenario)
                        if df is not None and not df.empty:
                            all_frames.append(df)

    if not all_frames:
        st.warning("No data returned for the selected parameters.")
        return

    out = pd.concat(all_frames, ignore_index=True)
    # Sort
    out.sort_values(["variable","model","scenario","date"], inplace=True)

    st.success(f"Fetched {len(out)} rows.")
    st.dataframe(out.head(100))

    # Simple chart for first selection
    try:
        sample = out[(out["variable"]==sel_vars[0]) & (out["model"]==sel_models[0]) & (out["scenario"]==sel_scen[0])]
        if not sample.empty:
            st.line_chart(sample.set_index('date')[['value']])
    except Exception:
        pass

    # Download CSV
    csv = out.to_csv(index=False)
    st.download_button(
        label="Download CSV",
        data=csv,
        file_name="gee_climate_timeseries.csv",
        mime="text/csv"
    )


if __name__ == "__main__":
    main()
