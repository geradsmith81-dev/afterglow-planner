# Afterglow

Sunrise, sunset, moonrise and moonset planner: your real skyline from open elevation data, Sun and Moon
from NASA JPL DE440s, and a forecast of how colourful the sky will be from Open-Meteo clouds along the
light path. Live satellite clouds (NASA GIBS) and Windy weather layers are built in.

Run locally: `pip install -r requirements.txt` then `streamlit run app.py`.
The JPL ephemeris `de440s.bsp` (32 MB) downloads into `ephem/` on first start.

Data: NASA JPL (DE440s, Horizons), AWS Terrain Tiles (SRTM, USGS 3DEP, GMTED2010...), Open-Meteo (CC BY 4.0),
CAMS, NASA GIBS, OpenStreetMap, OpenTopoMap, Esri, Windy.com. Map library: Leaflet 1.9.4 (BSD-2-Clause).
