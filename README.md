# Afterglow

Sunrise, sunset, moonrise and moonset planner: your real skyline from open elevation data, Sun and Moon
from NASA JPL DE440s, and a forecast of how colourful the sky will be from Open-Meteo clouds along the
light path. Live satellite clouds (NASA GIBS) and Windy weather layers are built in.

## Accuracy

- Rise and set times matched NASA JPL Horizons to within 0.43 s in testing.
- The sky-colour score is a rule of thumb and has not been validated against observed sunsets.

## Run locally

Install the exact, checksum-verified versions the app was tested with (Python 3.12 or newer):

```
python -m venv .venv
.venv\Scripts\python -m pip install --require-hashes --only-binary ":all:" --no-binary timezonefinder -r requirements.txt
.venv\Scripts\python -m streamlit run app.py --server.address 127.0.0.1
```

`requirements.in` lists the direct components; `requirements.txt` is the full lock with SHA-256
hashes (generated with `uv pip compile requirements.in --universal --python-version 3.12
--generate-hashes --only-binary :all: --no-binary timezonefinder`). The same lock serves Streamlit Community Cloud.

## Data and credits

NASA JPL (DE440s, Horizons), AWS Terrain Tiles (SRTM, USGS 3DEP, GMTED2010...), Open-Meteo (CC BY 4.0),
CAMS, NASA GIBS, OpenStreetMap, OpenTopoMap, Esri, Windy.com. Map library: Leaflet 1.9.4 (BSD-2-Clause).

## Security and privacy

- The Windows desktop copy of Afterglow listens on this computer only (127.0.0.1). "Share on this network.bat" can open it to the local network, protected by a new password each time; only the person at the computer sees Quit and data-clearing controls.
- The desktop copy keeps its data and logs in `%LOCALAPPDATA%\Afterglow`, checks its program files against `MANIFEST.sha256` at every start, and each release publishes SHA-256 checksums of its zips in `SHA256SUMS.txt`.
- All components are pinned to exact versions and installed with `--require-hashes`.
- The desktop-only code (`desktop.py`) does nothing on a hosted copy: no Quit button is shown there.
