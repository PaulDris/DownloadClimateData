import os
import json
import tempfile
import requests
from typing import List, Tuple

import streamlit as st
import pandas as pd

# Set wide layout for better UX
st.set_page_config(
    page_title="Climate Data Downloader",
    page_icon="🌍",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Optional mapping widgets
try:
    from streamlit_folium import st_folium
    import folium
    HAS_MAP = True
except Exception:
    HAS_MAP = False

# Earth Engine imports
try:
    import ee
except Exception as e:
    ee = None
    st.error("Google Earth Engine Python API not installed. Please install earthengine-api.")

APP_TITLE = "Earth Engine Climate Downloader (NASA/GDDP-CMIP6)"

# NASA/GDDP-CMIP6 is bias-corrected and downscaled to 0.25° (~25km) using quantile mapping
# Reference: https://www.nasa.gov/nex/gddp
# NASA/GDDP-CMIP6 structure: each image has these bands (all variables together)
AVAILABLE_BANDS = [
    "tas",      # Daily mean near-surface air temperature (K -> °C)
    "tasmax",   # Daily maximum near-surface air temperature (K -> °C)
    "tasmin",   # Daily minimum near-surface air temperature (K -> °C)
    "pr",       # Precipitation (kg m-2 s-1 -> mm/day)
    "hurs",     # Near-surface relative humidity (%)
    "huss",     # Near-surface specific humidity (1)
    "rsds",     # Surface downwelling shortwave radiation (W m-2)
    "rlds",     # Surface downwelling longwave radiation (W m-2)
    "sfcWind"   # Near-surface wind speed (m s-1)
]

# User-friendly names for display
BAND_NAMES = {
    "tas": "Temperature (Mean)",
    "tasmax": "Temperature (Max)",
    "tasmin": "Temperature (Min)",
    "pr": "Precipitation",
    "hurs": "Relative Humidity",
    "huss": "Specific Humidity",
    "rsds": "Solar Radiation (Shortwave)",
    "rlds": "Thermal Radiation (Longwave)",
    "sfcWind": "Wind Speed"
}

# Output units (after conversion)
BAND_UNITS = {
    "tas": "°C",
    "tasmax": "°C",
    "tasmin": "°C",
    "pr": "mm/day",
    "hurs": "%",
    "huss": "1",
    "rsds": "W m-2",
    "rlds": "W m-2",
    "sfcWind": "m s-1",
}

# Conversion functions
def convert_units(band: str, value: float) -> float:
    """Convert from raw NASA/GDDP units to user-friendly units."""
    if band in ["tas", "tasmax", "tasmin"]:
        # Kelvin to Celsius
        return value - 273.15
    elif band == "pr":
        # kg m-2 s-1 to mm/day
        # 1 kg m-2 s-1 = 86400 mm/day (since 1 kg/m2 = 1 mm of water)
        return value * 86400
    else:
        # No conversion needed
        return value


# Most important models - selected for regional representation and IPCC usage
KNOWN_MODELS = [
    "ACCESS-ESM1-5",   # Australia - good for Southern Hemisphere
    "CNRM-CM6-1",      # France/CNRM - European perspective
    "EC-Earth3",       # Europe consortium - multi-national
    "MPI-ESM1-2-LR",   # Germany - highly cited, reliable
    "MRI-ESM2-0",      # Japan - good for Asia-Pacific
    "CanESM5",         # Canada - widely used, well-validated
    "GFDL-ESM4",       # USA/NOAA - excellent historical performance
    "IPSL-CM6A-LR",    # France/IPSL - good for Europe
    "NorESM2-LM",      # Norway - good for Northern regions
    "UKESM1-0-LL"      # UK - comprehensive Earth system model
]

# Default models to select
DEFAULT_MODELS = [
    "ACCESS-ESM1-5",
    "CNRM-CM6-1",
    "EC-Earth3",
    "MPI-ESM1-2-LR",
    "MRI-ESM2-0"
]

# Model descriptions for display
MODEL_INFO = {
    "ACCESS-ESM1-5": "🇦🇺 Australia (Southern Hemisphere)",
    "CNRM-CM6-1": "�� France/CNRM (European)",
    "EC-Earth3": "�� Europe Consortium (Multi-national)",
    "MPI-ESM1-2-LR": "🇩🇪 Germany (Highly cited)",
    "MRI-ESM2-0": "🇯🇵 Japan (Asia-Pacific)",
    "CanESM5": "🇨🇦 Canada (Well-validated)",
    "GFDL-ESM4": "🇺🇸 USA/NOAA (High performance)",
    "IPSL-CM6A-LR": "🇫🇷 France/IPSL (Europe)",
    "NorESM2-LM": "🇳🇴 Norway (Northern regions)",
    "UKESM1-0-LL": "🇬🇧 UK (Comprehensive)"
}

KNOWN_SCENARIOS = [
    "historical",  # 1950-2014
    "ssp245",      # 2015-2100 - Medium emissions
    "ssp585"       # 2015-2100 - High emissions
]

# Scenario descriptions
SCENARIO_INFO = {
    "historical": "Historical (1950-2014)",
    "ssp245": "SSP2-4.5 - Medium emissions (Current policies)",
    "ssp585": "SSP5-8.5 - Very high emissions"
}

# Decades
DECADES = {
    f"{y}s ({y}-01-01 to {y+9}-12-31)": (f"{y}-01-01", f"{y+9}-12-31")
    for y in range(1950, 2100, 10)
}

COLL_ID = "NASA/GDDP-CMIP6"

# Default project - change this to your project ID
DEFAULT_PROJECT = "axial-edition-469618-t6"


def search_location(query: str) -> Tuple[float, float, str] | None:
    """Search for a location by name using forward geocoding."""
    try:
        # Use Nominatim (OpenStreetMap) for free geocoding
        url = f"https://nominatim.openstreetmap.org/search?format=json&q={query}&limit=1"
        headers = {'User-Agent': 'ClimateDataDownloader/1.0'}
        response = requests.get(url, headers=headers, timeout=5)
        if response.status_code == 200:
            results = response.json()
            if results:
                result = results[0]
                lat = float(result['lat'])
                lon = float(result['lon'])
                display_name = result.get('display_name', query)
                return lat, lon, display_name
    except Exception as e:
        st.error(f"Search error: {e}")
    return None


def get_location_name(lat: float, lon: float) -> str:
    """Get location name from coordinates using reverse geocoding."""
    try:
        # Use Nominatim (OpenStreetMap) for free reverse geocoding
        url = f"https://nominatim.openstreetmap.org/reverse?format=json&lat={lat}&lon={lon}&zoom=10"
        headers = {'User-Agent': 'ClimateDataDownloader/1.0'}
        response = requests.get(url, headers=headers, timeout=3)
        if response.status_code == 200:
            data = response.json()
            address = data.get('address', {})
            
            # Build location string from available components
            parts = []
            if 'city' in address:
                parts.append(address['city'])
            elif 'town' in address:
                parts.append(address['town'])
            elif 'village' in address:
                parts.append(address['village'])
            elif 'county' in address:
                parts.append(address['county'])
            
            if 'state' in address:
                parts.append(address['state'])
            if 'country' in address:
                parts.append(address['country'])
            
            return ", ".join(parts) if parts else f"{lat:.4f}, {lon:.4f}"
    except Exception:
        pass
    return f"{lat:.4f}, {lon:.4f}"


def _ensure_ee_initialized(project: str) -> Tuple[bool, str]:
    """Ensure Earth Engine is initialized once per session, supporting:
    - Local dev: existing OAuth or interactive ee.Authenticate()
    - Streamlit Cloud: service account via st.secrets or env vars
    Secrets/env supported:
      - st.secrets["gcp_service_account"]: full SA JSON dict
      - st.secrets["ee_service_account"], st.secrets["ee_private_key_json"]
      - EE_SERVICE_ACCOUNT, EE_PRIVATE_KEY_JSON env vars
      - Optional project override via EE_PROJECT env var
    """
    if ee is None:
        return False, "ee not installed"

    # Already initialized
    if st.session_state.get("ee_initialized"):
        return True, "already initialized"

    project = (os.environ.get("EE_PROJECT") or project or "").strip()
    if not project:
        return False, "Please specify a Cloud Project"

    # Helper: try initializing with given credentials
    def _try_init_with_credentials(credentials_obj=None) -> Tuple[bool, str]:
        try:
            if credentials_obj is not None:
                ee.Initialize(credentials_obj, project=project)
            else:
                ee.Initialize(project=project)
            st.session_state["ee_initialized"] = True
            return True, "initialized successfully"
        except Exception as e:
            return False, str(e)

    # 1) If we already have cached local OAuth creds, this will succeed directly
    ok, msg = _try_init_with_credentials(None)
    if ok:
        return True, "initialized with existing credentials"

    # 2) Try service account from Streamlit secrets or environment
    sa_email = None
    key_json_text = None
    try:
        # Preferred: full JSON dict under secrets.gcp_service_account
        if hasattr(st, "secrets") and "gcp_service_account" in st.secrets:
            sa_dict = dict(st.secrets["gcp_service_account"])  # copy in case it's a Secrets object
            sa_email = sa_dict.get("client_email")
            key_json_text = json.dumps(sa_dict)
        # Alternate: explicit keys in secrets
        elif hasattr(st, "secrets") and (
            "ee_service_account" in st.secrets and "ee_private_key_json" in st.secrets
        ):
            sa_email = st.secrets["ee_service_account"]
            key_json_text = st.secrets["ee_private_key_json"]
        # Environment variables (useful for local Docker or CI)
        elif os.environ.get("EE_SERVICE_ACCOUNT") and os.environ.get("EE_PRIVATE_KEY_JSON"):
            sa_email = os.environ.get("EE_SERVICE_ACCOUNT")
            key_json_text = os.environ.get("EE_PRIVATE_KEY_JSON")
    except Exception:
        pass

    if sa_email and key_json_text:
        try:
            # Write JSON to a temporary file (ee.ServiceAccountCredentials expects a path)
            with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json") as tf:
                tf.write(key_json_text)
                key_path = tf.name
            creds = ee.ServiceAccountCredentials(sa_email, key_path)
            ok, msg = _try_init_with_credentials(creds)
            # Clean up temp file if desired; keep for the session in case of lazy refresh
            try:
                os.unlink(key_path)
            except Exception:
                pass
            if ok:
                return True, f"initialized with service account {sa_email}"
        except Exception as e:
            # Fall through to next options
            last_sa_err = str(e)
    else:
        last_sa_err = "no service account credentials provided"

    # 3) On Streamlit Cloud, interactive OAuth is not possible
    running_on_streamlit_cloud = bool(os.environ.get("STREAMLIT_SERVER_ENABLED") or os.environ.get("STREAMLIT_RUNTIME"))
    if running_on_streamlit_cloud:
        return False, f"Streamlit deploy requires a service account. {last_sa_err}"

    # 4) Local fallback: prompt OAuth
    try:
        ee.Authenticate()
        ok, msg = _try_init_with_credentials(None)
        if ok:
            return True, "authenticated via OAuth"
        return False, msg
    except Exception as e:
        return False, f"OAuth failed and no service account available: {e}"


def _init_ee(project: str | None = None) -> Tuple[bool, str]:
    """Legacy function - now just calls _ensure_ee_initialized."""
    if not project:
        project = DEFAULT_PROJECT
    return _ensure_ee_initialized(project)


def list_dynamic_options() -> Tuple[List[str], List[str]]:
    """Return (models, scenarios) from the collection."""
    if ee is None:
        return KNOWN_MODELS, KNOWN_SCENARIOS
    try:
        coll = ee.ImageCollection(COLL_ID)
        # Need to sample more images to get all unique values
        # Or just use the known comprehensive lists
        # Since dynamic discovery is unreliable, use known lists
        return KNOWN_MODELS, KNOWN_SCENARIOS
    except Exception:
        return KNOWN_MODELS, KNOWN_SCENARIOS


def ui_sidebar():
    # Sidebar header
    st.sidebar.title("🌍 Climate Data Downloader")
    st.sidebar.markdown("**NASA/GDDP-CMIP6** • Bias-corrected & Downscaled")
    
    # Initialize session state for project if not set
    if "ee_project" not in st.session_state:
        st.session_state["ee_project"] = DEFAULT_PROJECT
    
    # Auto-initialize EE on first run
    if "ee_initialized" not in st.session_state:
        proj = st.session_state["ee_project"]
        ok, msg = _ensure_ee_initialized(proj)
        if ok:
            st.sidebar.success(f"✓ Connected to Earth Engine")
        else:
            st.sidebar.warning(f"⚠ EE Init failed: {msg}")
    
    # EE setup panel (collapsed by default since we auto-init)
    with st.sidebar.expander("⚙️ Earth Engine Settings", expanded=False):
        st.markdown(f"""
**Current Project:** `{st.session_state.get("ee_project", DEFAULT_PROJECT)}`

Your project is automatically connected.
        """)
        ee_proj = st.text_input("EE Cloud Project", value=st.session_state.get("ee_project", DEFAULT_PROJECT))
        if st.button("Change Project & Reconnect"):
            st.session_state["ee_project"] = ee_proj.strip()
            st.session_state["ee_initialized"] = False  # Force re-init
            proj = st.session_state["ee_project"]
            ok, msg = _ensure_ee_initialized(proj)
            st.write(f"Reconnect: {ok}, msg: {msg}")
            if ok and ee is not None:
                try:
                    n = ee.ImageCollection(COLL_ID).limit(1).size().getInfo()
                    st.success(f"Dataset reachable! (test size: {n})")
                except Exception as e:
                    st.error(f"Dataset check failed: {e}")
            st.rerun()
    
    # Check if initialized
    if not st.session_state.get("ee_initialized", False):
        st.sidebar.error("Earth Engine not initialized. Please check settings.")
        st.stop()

    st.sidebar.divider()
    
    models, scenarios = list_dynamic_options()

    # === LOCATION SECTION ===
    st.sidebar.subheader("📍 Location")
    
    # Location search
    search_query = st.sidebar.text_input(
        "🔍 Search location", 
        placeholder="e.g., Paris, London, Tokyo...",
        help="Search for any city, address, or place name"
    )
    
    if st.sidebar.button("Search", use_container_width=True):
        if search_query:
            with st.spinner("Searching..."):
                result = search_location(search_query)
                if result:
                    lat, lon, display_name = result
                    st.session_state["coords"] = f"{lat:.5f},{lon:.5f}"
                    st.session_state["location_name"] = display_name
                    st.sidebar.success(f"✓ Found: {display_name}")
                    st.rerun()
                else:
                    st.sidebar.error("❌ Location not found. Try a different search term.")
        else:
            st.sidebar.warning("Please enter a location to search")
    
    st.sidebar.caption("Or enter coordinates manually:")
    
    # Initialize coords in session state if not present
    if "coords" not in st.session_state:
        st.session_state["coords"] = "51.5074,-0.1278"
    
    coords = st.sidebar.text_input(
        "Coordinates (lat, lon)", 
        value=st.session_state.get("coords", "51.5074,-0.1278"),
        help="Click map in main area or enter coordinates"
    )
    
    try:
        lat0, lon0 = [float(v.strip()) for v in coords.split(",")]
    except Exception:
        lat0, lon0 = 51.5074, -0.1278
    
    # Show location name if available
    if "location_name" in st.session_state:
        st.sidebar.info(f"📍 {st.session_state['location_name']}")

    st.sidebar.divider()

    # === TIME PERIODS ===
    st.sidebar.subheader("📅 Time Periods")
    st.sidebar.caption("Historical: 1950-2014 | SSP: 2015-2100")
    decades = st.sidebar.multiselect(
        "Select decades", 
        list(DECADES.keys()), 
        default=["2000s (2000-01-01 to 2009-12-31)"],
        help="Choose one or more decades to download"
    )

    st.sidebar.divider()

    # === VARIABLES ===
    st.sidebar.subheader("🌡️ Climate Variables")
    
    # Create options with friendly names
    variable_options = [f"{BAND_NAMES[b]} ({b})" for b in AVAILABLE_BANDS]
    default_vars = [f"{BAND_NAMES[b]} ({b})" for b in ["tasmax", "tasmin", "pr"]]
    
    selected_vars = st.sidebar.multiselect(
        "Select variables", 
        variable_options,
        default=default_vars,
        help="All values converted to user-friendly units (°C, mm/day)"
    )
    
    # Extract the technical band names from selections
    sel_bands = [v.split("(")[-1].rstrip(")") for v in selected_vars]
    
    with st.sidebar.expander("ℹ️ Variable Details"):
        for band in sel_bands:
            st.write(f"**{BAND_NAMES[band]}** ({band}): {BAND_UNITS.get(band, '')}")

    st.sidebar.divider()

    # === MODELS ===
    st.sidebar.subheader("🔬 Climate Models")
    
    # Create options with descriptions
    model_options = [f"{m} - {MODEL_INFO[m]}" for m in models]
    
    # Use DEFAULT_MODELS for defaults (ensure they exist in current models list)
    default_model_list = [m for m in DEFAULT_MODELS if m in models]
    if not default_model_list:
        # Fallback to first models if defaults aren't available
        default_model_list = models[:5] if len(models) >= 5 else models
    
    default_models = [f"{m} - {MODEL_INFO[m]}" for m in default_model_list]
    
    selected_models = st.sidebar.multiselect(
        "Select models", 
        model_options,
        default=default_models,
        help="5 recommended models selected by default"
    )
    
    # Extract the technical model names from selections
    sel_models = [m.split(" - ")[0] for m in selected_models]
    
    # === OUTPUT OPTIONS ===
    st.sidebar.markdown("**Output Options:**")
    col1, col2 = st.sidebar.columns(2)
    with col1:
        include_individual = st.checkbox(
            "Individual", 
            value=True,
            help="Include each model separately"
        )
    with col2:
        include_ensemble = st.checkbox(
            "Ensemble", 
            value=True,
            help="Multi-model mean (recommended)"
        )
    
    if not include_individual and not include_ensemble:
        st.sidebar.error("⚠️ Select at least one output option")

    st.sidebar.divider()

    # === SCENARIOS ===
    st.sidebar.subheader("🌐 Scenarios")
    
    # Filter scenarios based on selected decades
    has_historical_decades = False
    has_future_decades = False
    
    if decades:
        for decade_str in decades:
            # Extract start year from decade string (e.g., "2000s (2000-01-01..." -> 2000)
            start_year = int(decade_str.split("s")[0])
            if start_year <= 2010:  # Historical ends 2014, so 2010s partially overlaps
                has_historical_decades = True
            if start_year >= 2010:  # SSPs start 2015, so 2010s partially overlaps
                has_future_decades = True
    
    # Filter available scenarios
    available_scenarios = []
    for s in scenarios:
        if s == "historical" and has_historical_decades:
            available_scenarios.append(s)
        elif s != "historical" and has_future_decades:
            available_scenarios.append(s)
    
    # If no decades selected, show all scenarios
    if not decades:
        available_scenarios = scenarios
    
    # Create options with descriptions
    scenario_options = [SCENARIO_INFO.get(s, s) for s in available_scenarios]
    
    # Smart defaults based on available scenarios
    if "historical" in available_scenarios and "ssp245" in available_scenarios:
        default_scen_keys = ["historical", "ssp245"]
    elif "historical" in available_scenarios:
        default_scen_keys = ["historical"]
    elif "ssp245" in available_scenarios:
        default_scen_keys = ["ssp245"]
    else:
        default_scen_keys = available_scenarios[:1] if available_scenarios else []
    
    default_scenarios = [SCENARIO_INFO.get(s, s) for s in default_scen_keys]
    
    # Show info about filtering
    if decades and len(available_scenarios) < len(scenarios):
        filtered_out = [s for s in scenarios if s not in available_scenarios]
        if filtered_out:
            st.sidebar.caption(f"ℹ️ Filtered out incompatible: {', '.join(filtered_out)}")
    
    selected_scenarios = st.sidebar.multiselect(
        "Select scenarios", 
        scenario_options,
        default=default_scenarios,
        help="Auto-filtered based on selected decades"
    )
    
    # Extract the technical scenario names from selections
    scenario_mapping = {SCENARIO_INFO.get(s, s): s for s in available_scenarios}
    sel_scen = [scenario_mapping[s] for s in selected_scenarios]

    st.sidebar.divider()

    # === DISPLAY OPTIONS ===
    st.sidebar.subheader("👁️ Display")
    show_charts = st.sidebar.checkbox(
        "Show preview charts", 
        value=False, 
        help="Generate charts after fetching (slower)"
    )

    st.sidebar.divider()

    # === FETCH BUTTON ===
    run = st.sidebar.button("🚀 Fetch Data", type="primary", use_container_width=True)
    
    # Store map state for main area
    map_coords = (lat0, lon0)
    
    return run, (coords, decades, sel_bands, sel_models, sel_scen, include_individual, include_ensemble, show_charts, map_coords)


def clamp_dates_for_scenario(start_date: str, end_date: str, scenario: str) -> Tuple[str, str]:
    """Clamp dates to historical (1950-2014) or SSP (2015-2100)."""
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
                           bands: List[str], model: str, scenario: str,
                           scale: int = 25000) -> pd.DataFrame:
    """Fetch daily time series for a point. Returns rows: date, band, value, model, scenario."""
    point = ee.Geometry.Point([lon, lat])
    coll = (ee.ImageCollection(COLL_ID)
            .filter(ee.Filter.eq('model', model))
            .filter(ee.Filter.eq('scenario', scenario))
            .filterDate(start, end))
    
    # Check collection size first
    try:
        coll_size = coll.size().getInfo()
        if coll_size == 0:
            st.warning(f"No images found for {model}/{scenario} in {start} to {end}")
            return pd.DataFrame(columns=["date", "band", "value", "model", "scenario"])
    except Exception as e:
        st.warning(f"Collection size check failed for {model}/{scenario}: {e}")
        return pd.DataFrame(columns=["date", "band", "value", "model", "scenario"])
    
    # Check which bands are actually available for this model
    try:
        first_img = coll.first()
        available_bands = first_img.bandNames().getInfo()
        bands_to_fetch = [b for b in bands if b in available_bands]
        if not bands_to_fetch:
            st.warning(f"None of the requested bands {bands} are available in {model}. Available: {available_bands}")
            return pd.DataFrame(columns=["date", "band", "value", "model", "scenario"])
        if len(bands_to_fetch) < len(bands):
            missing = [b for b in bands if b not in available_bands]
            st.info(f"{model} missing bands: {missing}. Fetching: {bands_to_fetch}")
    except Exception as e:
        st.warning(f"Could not check available bands for {model}/{scenario}: {e}")
        bands_to_fetch = bands  # Try anyway
    
    # Select only available bands
    coll = coll.select(bands_to_fetch)
    
    # Use getRegion to extract time series
    try:
        arr = coll.getRegion(point, scale).getInfo()
    except Exception as e:
        st.warning(f"getRegion failed for {model}/{scenario}: {e}")
        return pd.DataFrame(columns=["date", "band", "value", "model", "scenario"])
    
    if not arr or len(arr) < 2:
        st.warning(f"getRegion returned no data for {model}/{scenario}")
        return pd.DataFrame(columns=["date", "band", "value", "model", "scenario"])
    
    header, rows = arr[0], arr[1:]
    time_idx = header.index('time') if 'time' in header else None
    if time_idx is None:
        st.warning(f"No 'time' column in getRegion result for {model}/{scenario}")
        return pd.DataFrame(columns=["date", "band", "value", "model", "scenario"])
    
    # Build records
    recs = []
    bands_found = set()
    for r in rows:
        try:
            t = pd.to_datetime(r[time_idx], unit='ms', utc=True).tz_convert(None)
            date_str = t.date().isoformat()
        except Exception:
            continue
        
        for band in bands_to_fetch:
            if band in header:
                idx = header.index(band)
                val = r[idx]
                if val is not None:
                    bands_found.add(band)
                    # Apply unit conversions
                    val = convert_units(band, float(val))
                    
                    recs.append({
                        "date": date_str,
                        "band": band,
                        "value": val,
                        "model": model,
                        "scenario": scenario
                    })
    
    df = pd.DataFrame.from_records(recs)
    if not df.empty:
        st.success(f"✓ {model}/{scenario}: {len(df)} records from bands: {sorted(bands_found)}")
    else:
        st.warning(f"No records created for {model}/{scenario}. Bands in header: {[b for b in bands_to_fetch if b in header]}")
    return df


def main():
    run, (coords, decades, sel_bands, sel_models, sel_scen, include_individual, include_ensemble, show_charts, map_coords) = ui_sidebar()
    
    # === MAIN AREA: Map and Info ===
    st.title("🌍 Climate Data Downloader")
    st.markdown("**NASA/GDDP-CMIP6** - Bias-corrected & downscaled daily climate projections")
    
    # Get coordinates
    try:
        lat, lon = [float(v.strip()) for v in coords.split(",")]
    except Exception:
        lat, lon = map_coords
    
    # Get location name
    location_name = get_location_name(lat, lon)
    st.session_state["location_name"] = location_name
    
    # Display map in main area
    if HAS_MAP:
        col1, col2 = st.columns([2, 1])
        
        with col1:
            st.subheader(f"📍 {location_name}")
            m = folium.Map(location=[lat, lon], zoom_start=6, control_scale=True)
            folium.Marker(
                [lat, lon], 
                popup=f"{location_name}<br>{lat:.4f}, {lon:.4f}",
                tooltip="Click to select location",
                icon=folium.Icon(color='red', icon='info-sign')
            ).add_to(m)
            
            map_state = st_folium(m, height=400, width=None, returned_objects=["last_clicked"])
            
            if map_state and map_state.get("last_clicked"):
                new_lat = map_state["last_clicked"]["lat"]
                new_lon = map_state["last_clicked"]["lng"]
                st.session_state["coords"] = f"{new_lat:.5f},{new_lon:.5f}"
                st.rerun()
        
        with col2:
            st.subheader("ℹ️ About")
            st.markdown("""
**Data Source:**  
NASA/GDDP-CMIP6

**Features:**
- ✓ Bias-corrected (quantile mapping vs ERA5)
- ✓ 0.25° resolution (~25km)
- ✓ Daily temporal resolution
- ✓ 8 key climate models
- ✓ Historical + SSP scenarios

**Units:**
- Temperature: °C
- Precipitation: mm/day
            """)
    else:
        st.info(f"📍 Selected location: {location_name} ({lat:.4f}, {lon:.4f})")
    
    st.divider()
    
    # Check if we have downloads ready (from previous fetch)
    if st.session_state.get("downloads_ready", False) and not run:
        # Show the download section without fetching new data
        st.info("💾 Your data is ready for download below. Change settings and click **Fetch Data** to get new data.")
        out = st.session_state.get("cached_dataframe")
        lat = st.session_state.get("cached_lat", lat)
        lon = st.session_state.get("cached_lon", lon)
        location_name = st.session_state.get("cached_location", location_name)
        include_ensemble = st.session_state.get("cached_ensemble", False)
        sel_models = st.session_state.get("cached_models", [])
        sel_bands = st.session_state.get("cached_bands", [])
        show_charts = False  # Don't show charts for cached data
        # Skip to download section at the end
    elif not run:
        st.info("👈 Configure options in the sidebar and click **Fetch Data** to download climate data")
        return
    else:
        # Validation
        if not sel_bands:
            st.error("Please select at least one variable (band).")
            return
        if not sel_models:
            st.error("Please select at least one model.")
            return
        if not sel_scen:
            st.error("Please select at least one scenario.")
            return
        if not decades:
            st.error("Please select at least one decade.")
            return
        if not include_individual and not include_ensemble:
            st.error("Please select at least one output option (Individual Models or Ensemble Mean).")
            return
        if include_ensemble and len(sel_models) < 2:
            st.warning("⚠️ Ensemble mean requires at least 2 models. Either select more models or disable ensemble mean.")
            return

        # Show what was selected in a clean format
        st.subheader("📋 Data Fetch Configuration")
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Location", location_name)
            st.caption(f"{lat:.4f}, {lon:.4f}")
        with col2:
            st.metric("Variables", len(sel_bands))
            st.caption(", ".join([BAND_NAMES[b] for b in sel_bands]))
        with col3:
            st.metric("Models", len(sel_models))
            st.caption("Individual" if include_individual else "" + (" + Ensemble" if include_ensemble else ""))
        
        with st.expander("📊 Full Configuration", expanded=False):
            st.write(f"**Decades:** {', '.join(decades)}")
            st.write(f"**Models:** {', '.join([f'{m} ({MODEL_INFO[m]})' for m in sel_models])}")
            st.write(f"**Scenarios:** {', '.join([SCENARIO_INFO.get(s, s) for s in sel_scen])}")
            st.write(f"**Variables:** {', '.join([f'{BAND_NAMES[b]} ({BAND_UNITS[b]})' for b in sel_bands])}")

        date_ranges = [DECADES[d] for d in decades]

        st.info("⏳ Fetching data from Earth Engine... This may take a while for many combinations.")

        all_frames = []
        total = len(sel_scen) * len(date_ranges) * len(sel_models)
        progress = st.progress(0, text="Starting download...")
        status_placeholder = st.empty()
        error_log = []
        count = 0
        
        for scenario in sel_scen:
            for (start, end) in date_ranges:
                s_adj, e_adj = clamp_dates_for_scenario(start, end, scenario)
                if not s_adj:
                    msg = f"⚠️ Skipping {SCENARIO_INFO.get(scenario, scenario)} for decade {start} to {end} (date range incompatible)"
                    status_placeholder.warning(msg)
                    error_log.append(msg)
                    continue
                for model in sel_models:
                    count += 1
                    model_display = f"{model} ({MODEL_INFO[model].split(' ')[0]})"
                    progress.progress(count / total, text=f"Fetching {count}/{total}: {model_display} • {scenario} • {s_adj[:4]}-{e_adj[:4]}")
                    df = fetch_point_timeseries(lat, lon, s_adj, e_adj, sel_bands, model, scenario)
                    if df is not None and not df.empty:
                        all_frames.append(df)
                        status_placeholder.success(f"✓ {model_display} / {scenario}: {len(df)} rows")
                    else:
                        msg = f"⚠️ {model_display} / {scenario} / {s_adj[:4]}-{e_adj[:4]}: No data returned"
                        status_placeholder.warning(msg)
                        error_log.append(msg)

        progress.empty()
        status_placeholder.empty()

        if not all_frames:
            st.error("❌ No data returned for the selected parameters.")
            
            st.subheader("🔍 Troubleshooting")
            
            # Show what was attempted
            st.write("**Attempted to fetch:**")
            st.write(f"- Location: {lat:.4f}, {lon:.4f} ({location_name})")
            st.write(f"- Models: {', '.join(sel_models)}")
            st.write(f"- Scenarios: {', '.join([SCENARIO_INFO.get(s, s) for s in sel_scen])}")
            st.write(f"- Decades: {', '.join(decades)}")
            st.write(f"- Variables: {', '.join([BAND_NAMES[b] for b in sel_bands])}")
            
            # Show error log
            if error_log:
                with st.expander("⚠️ Error Details", expanded=True):
                    for err in error_log:
                        st.write(err)
            
            # Common issues
            st.info(
                """
**Common Issues:**
1. Scenario/Decade mismatch: Historical only covers 1950-2014, SSP scenarios cover 2015-2100
2. Model availability: Not all models have data for all scenarios
3. Earth Engine timeout: Try selecting fewer decades or models

**Suggestions:**
- For historical data, select decades from 1950-2010
- For SSP scenarios, select decades from 2020-2090
- Try selecting only 1-2 decades at a time
- Reduce number of variables if timeout occurs
                """
            )
            return

        # Combine all fetched data
        all_data = pd.concat(all_frames, ignore_index=True)
        all_data.sort_values(["band", "model", "scenario", "date"], inplace=True)
        
        # Build output based on user selections
        output_frames = []
        
        # Add individual models if requested
        if include_individual:
            output_frames.append(all_data)
        
        # Calculate and add ensemble mean if requested
        if include_ensemble and len(sel_models) > 1:
            st.info(f"Calculating multi-model ensemble mean from {len(sel_models)} models...")
            ensemble_frames = []
            
            for scenario in sel_scen:
                for band in sel_bands:
                    # Get data for this scenario and band across all models
                    subset = all_data[(all_data["scenario"] == scenario) & (all_data["band"] == band)]
                    
                    if not subset.empty:
                        # Group by date and calculate mean across models
                        ensemble = subset.groupby("date")["value"].mean().reset_index()
                        ensemble["band"] = band
                        ensemble["model"] = "ENSEMBLE-MEAN"
                        ensemble["scenario"] = scenario
                        ensemble_frames.append(ensemble)
            
            if ensemble_frames:
                ensemble_df = pd.concat(ensemble_frames, ignore_index=True)
                output_frames.append(ensemble_df)
                
                # Add info box showing which models are in the ensemble
                model_list = ", ".join(sel_models)
                st.success(f"✓ Added ensemble mean for {len(ensemble_frames)} band×scenario combinations")
                st.info(f"**Ensemble Mean includes {len(sel_models)} models:**\n\n{model_list}")
        
        # Combine final output
        out = pd.concat(output_frames, ignore_index=True)
        out.sort_values(["band", "model", "scenario", "date"], inplace=True)

        st.success(f"Fetched {len(out)} rows total.")
        
        # Cache the dataframe and settings for downloads
        st.session_state["cached_dataframe"] = out
        st.session_state["cached_lat"] = lat
        st.session_state["cached_lon"] = lon
        st.session_state["cached_location"] = location_name
        st.session_state["cached_ensemble"] = include_ensemble
        st.session_state["cached_models"] = sel_models
        st.session_state["cached_bands"] = sel_bands
    
    # Show metadata section if ensemble was included
    if include_ensemble and len(sel_models) > 1:
        with st.expander("ℹ️ Dataset Information", expanded=False):
            st.markdown(f"""
**Units (all values converted to user-friendly units):**
- Temperature variables (tas, tasmax, tasmin): **°C**
- Precipitation (pr): **mm/day**
- Other variables: as listed in variable selection

**Ensemble Mean:**
- Model name in CSV: `ENSEMBLE-MEAN`
- Calculated as arithmetic mean across {len(sel_models)} models:
  - {chr(10).join(f'  • {m}' for m in sel_models)}
- Mean is computed for each date, variable, and scenario independently
            """)
    
    # Data preview (collapsed by default for large datasets)
    with st.expander("📊 Data Preview (first 100 rows)", expanded=len(out) < 1000):
        st.dataframe(out.head(100))

    # Charts (based on sidebar checkbox)
    if show_charts:
        st.subheader("Preview Charts")
        for band in sel_bands:
            st.write(f"**{band}** ({BAND_UNITS.get(band, '')})")
            
            # Determine what to display based on user selection
            if include_ensemble and not include_individual:
                # Only ensemble
                display_model = "ENSEMBLE-MEAN"
                st.caption(f"Showing ensemble mean for {sel_scen[0]}")
            elif include_ensemble and include_individual:
                # Both - prefer ensemble for chart
                display_model = "ENSEMBLE-MEAN"
                st.caption(f"Showing ensemble mean for {sel_scen[0]} (individual models also in CSV)")
            else:
                # Only individual models
                display_model = sel_models[0]
                st.caption(f"Showing {display_model} for {sel_scen[0]}")
            
            sample = out[(out["band"] == band) & (out["model"] == display_model) & (out["scenario"] == sel_scen[0])]
            if not sample.empty:
                chart_data = sample.set_index('date')[['value']].rename(columns={'value': band})
                st.line_chart(chart_data)
            else:
                                st.caption(f"No data for {band} / {display_model} / {sel_scen[0]}")

    # Store data in session state to prevent resets
    if "download_data" not in st.session_state:
        st.session_state["download_data"] = None
    if "downloads_ready" not in st.session_state:
        st.session_state["downloads_ready"] = False
    
    # Generate unique hash for current dataset
    data_hash = hash(out.to_csv())
    
    # Only prepare download data once (or when data changes)
    if st.session_state["download_data"] is None or st.session_state.get("data_hash") != data_hash:
        with st.spinner("Preparing download files..."):
            # Calculate file info
            total_rows = len(out)
            total_size_mb = len(out.to_csv(index=False).encode('utf-8')) / (1024 * 1024)
            unique_models = sorted(out["model"].unique())
            
            # Create base metadata
            def create_metadata(models_included=None):
                lines = [
                    "# ============================================================================",
                    "# NASA/GDDP-CMIP6 Climate Data Download",
                    "# ============================================================================",
                    f"# Location: {lat}°N, {lon}°E",
                    f"# Place: {location_name}",
                    f"# Generated: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}",
                    "# ",
                    "# DATA COLUMNS:",
                    "#   date      - Date in YYYY-MM-DD format",
                    "#   band      - Climate variable (see VARIABLES section below)",
                    "#   model     - Climate model name (or ENSEMBLE-MEAN)",
                    "#   scenario  - Emissions scenario (historical, ssp245, ssp585)",
                    "#   value     - Measured value in units specified below",
                    "# ",
                    "# VARIABLES & UNITS (converted from raw NASA data):",
                    "#   tas       - Daily Mean Temperature (°C)",
                    "#   tasmax    - Daily Maximum Temperature (°C)",
                    "#   tasmin    - Daily Minimum Temperature (°C)",
                    "#   pr        - Precipitation (mm/day)",
                    "#   hurs      - Near-Surface Relative Humidity (%)",
                    "#   huss      - Near-Surface Specific Humidity (kg/kg)",
                    "#   rsds      - Surface Downwelling Shortwave Radiation (W/m²)",
                    "#   rlds      - Surface Downwelling Longwave Radiation (W/m²)",
                    "#   sfcWind   - Near-Surface Wind Speed (m/s)",
                    "# ",
                    "# SCENARIOS:",
                    "#   historical - Historical observations (1950-2014)",
                    "#   ssp245     - SSP2-4.5: Medium emissions / Current policies trajectory",
                    "#   ssp585     - SSP5-8.5: High emissions / Business as usual",
                    "# "
                ]
                
                if models_included:
                    if "ENSEMBLE-MEAN" in models_included and len(models_included) > 1:
                        actual_models = [m for m in models_included if m != "ENSEMBLE-MEAN"]
                        lines.extend([
                            "# MODELS:",
                            f"#   This file includes {len(actual_models)} climate models:",
                        ])
                        for m in actual_models:
                            lines.append(f"#     • {m}")
                        lines.extend([
                            "# ",
                            "#   ENSEMBLE-MEAN is the arithmetic average across all models",
                            "#   for each date, variable, and scenario combination.",
                            "# "
                        ])
                    elif len(models_included) == 1 and models_included[0] != "ENSEMBLE-MEAN":
                        lines.extend([
                            "# MODEL:",
                            f"#   {models_included[0]}",
                            "# "
                        ])
                    elif models_included == ["ENSEMBLE-MEAN"]:
                        lines.extend([
                            "# MODEL:",
                            "#   ENSEMBLE-MEAN (multi-model average)",
                            "# "
                        ])
                
                lines.extend([
                    "# DATA SOURCE:",
                    "#   NASA Earth Exchange Global Daily Downscaled Climate Projections",
                    "#   (NEX-GDDP-CMIP6)",
                    "#   Resolution: 0.25° (~25 km)",
                    "#   More info: https://www.nccs.nasa.gov/services/data-collections/land-based-products/nex-gddp-cmip6",
                    "# ============================================================================",
                    "#"
                ])
                return "\n".join(lines) + "\n"
            
            # Pre-generate all download files
            download_files = {}
            
            # Individual model files
            for model in unique_models:
                model_data = out[out["model"] == model]
                model_rows = len(model_data)
                model_size_mb = len(model_data.to_csv(index=False).encode('utf-8')) / (1024 * 1024)
                
                metadata_text = create_metadata([model])
                csv_data = model_data.to_csv(index=False)
                csv_with_metadata = metadata_text + csv_data
                
                model_clean = model.replace(" ", "_").replace("-", "_")
                model_display = model.split("-")[0] if model != "ENSEMBLE-MEAN" else "ENSEMBLE"
                
                download_files[model] = {
                    "data": csv_with_metadata,
                    "filename": f"gddp_cmip6_{model_clean}_{lat:.2f}_{lon:.2f}.csv",
                    "label": f"📄 {model_display}\n{model_rows:,} rows • {model_size_mb:.1f} MB",
                    "size_mb": model_size_mb
                }
            
            # Combined file
            metadata_text = create_metadata(unique_models)
            csv_data = out.to_csv(index=False)
            csv_with_metadata = metadata_text + csv_data
            
            download_files["_combined"] = {
                "data": csv_with_metadata,
                "filename": f"gddp_cmip6_all_models_{lat:.2f}_{lon:.2f}.csv",
                "label": f"⬇️ Download All Models Combined ({total_size_mb:.1f} MB)",
                "size_mb": total_size_mb
            }
            
            # Store in session state
            st.session_state["download_data"] = download_files
            st.session_state["data_hash"] = data_hash
            st.session_state["download_info"] = {
                "total_rows": total_rows,
                "total_size_mb": total_size_mb,
                "unique_models": unique_models
            }
            st.session_state["downloads_ready"] = True
    
    # Display download section (using cached data) - always show if ready
    if st.session_state.get("downloads_ready", False):
        st.subheader("📥 Download Data")
        info = st.session_state["download_info"]
        st.info(f"**Dataset:** {info['total_rows']:,} rows • {len(info['unique_models'])} models • ~{info['total_size_mb']:.1f} MB total")
        
        # Default: Split by model (more reliable for large datasets)
        st.markdown("### 📂 Download Individual Model Files")
        st.caption("✓ Recommended for large datasets • More reliable • Easier to process")
        
        # Create columns for buttons (3 per row)
        cols_per_row = 3
        download_data = st.session_state["download_data"]
        unique_models = info["unique_models"]
        
        for i in range(0, len(unique_models), cols_per_row):
            cols = st.columns(cols_per_row)
            for j, model in enumerate(unique_models[i:i+cols_per_row]):
                file_info = download_data[model]
                with cols[j]:
                    st.download_button(
                        label=file_info["label"],
                        data=file_info["data"],
                        file_name=file_info["filename"],
                        mime="text/csv",
                        key=f"dl_{model}_{data_hash}",
                        use_container_width=True
                    )
        
        # Optional: Combined file (only for smaller datasets)
        st.markdown("---")
        with st.expander("📦 Alternative: Download Combined File (all models in one)", expanded=False):
            if info["total_size_mb"] > 50:
                st.warning(f"⚠️ Combined file is large ({info['total_size_mb']:.1f} MB). Individual downloads recommended to avoid timeouts.")
            
            combined_info = download_data["_combined"]
            st.download_button(
                label=combined_info["label"],
                data=combined_info["data"],
                file_name=combined_info["filename"],
                mime="text/csv",
                key=f"dl_combined_{data_hash}",
                use_container_width=True
            )


if __name__ == "__main__":
    main()
