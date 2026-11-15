# Afterglow

Sunrise, sunset, moonrise and moonset planner: your real skyline from open elevation data, Sun and Moon
from NASA JPL DE440s, and a forecast of how colourful the sky will be from Open-Meteo clouds along the
light path. Live satellite clouds (NASA GIBS) and Windy weather layers are built in.

## Accuracy

- Rise and set times matched NASA JPL Horizons to within 0.43 s in testing.
- The sky-colour score is a rule of thumb and has not been validated against observed sunsets.

## Run locally

`pip install -r requirements.txt` then `streamlit run app.py`.
The JPL ephemeris `de440s.bsp` (32 MB) downloads into `ephem/` on first start.

## Data and credits

NASA JPL (DE440s, Horizons), AWS Terrain Tiles (SRTM, USGS 3DEP, GMTED2010...), Open-Meteo (CC BY 4.0),
CAMS, NASA GIBS, OpenStreetMap, OpenTopoMap, Esri, Windy.com. Map library: Leaflet 1.9.4 (BSD-2-Clause).
