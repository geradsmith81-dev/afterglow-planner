"""Afterglow - eclipse world map (where an eclipse is seen, central line, your position)."""
import os

import streamlit as st

HERE = os.path.dirname(os.path.abspath(__file__))


def _read(name):
    with open(os.path.join(HERE, 'assets', name), encoding='utf-8') as f:
        return f.read()


_COMPONENT = st.components.v2.component(
    'afterglow_eventmap',
    js=_read('leaflet.js') + '\n;\n' + _read('eventmap.js'),
    css=_read('leaflet.css') + '\n' + _read('planner.css') + '\n' + _read('nightmap.css'),
    isolate_styles=False,
)


def show(data, on_pick, key='eventmap'):
    return _COMPONENT(data=data, key=key, on_pick_change=on_pick, width='stretch', height='content')
