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


# ------------------------------------------------------------------------------------------
# A table whose rows can be tapped to choose one item (used for the eclipse list).
# The table HTML is built in Python (same look as the other tables); the browser side only marks
# the chosen row and sends its id back.
_ROWPICK_JS = """
export default function (component) {
  const { data, parentElement, setStateValue } = component;
  let box = parentElement.querySelector('.ag-rowpick');
  if (!box) { box = document.createElement('div'); box.className = 'ag-rowpick'; parentElement.appendChild(box); }
  box.innerHTML = data.html;
  const rows = Array.from(box.querySelectorAll('tr[data-id]'));
  const mark = (id) => rows.forEach((r) => {
    const on = r.dataset.id === id;
    r.classList.toggle('ag-sel', on);
    r.setAttribute('aria-selected', on ? 'true' : 'false');
  });
  let current = data.selected;
  mark(current);
  rows.forEach((r) => {
    r.tabIndex = 0;
    r.setAttribute('role', 'button');
    const choose = () => {
      if (r.dataset.id === current) return;
      current = r.dataset.id;
      mark(current);
      setStateValue('row', current);
    };
    r.addEventListener('click', choose);
    r.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); choose(); } });
  });
}
"""
_ROWPICK_CSS = """
.ag-rowpick tr[data-id] { cursor: pointer; }
.ag-rowpick tr[data-id]:hover td { background: #18233a; }
.ag-rowpick tr[data-id]:focus-visible { outline: 2px solid #ffcd9c; outline-offset: -2px; }
.ag-rowpick tr.ag-sel td { background: #24365a; }
.ag-rowpick tr.ag-sel td:first-child { box-shadow: inset 4px 0 0 #ffcd9c; }
"""
_ROWPICK = st.components.v2.component('afterglow_rowpick', js=_ROWPICK_JS, css=_ROWPICK_CSS, isolate_styles=False)


def row_picker(table_html, selected_id, key):
    """Show a clickable table; returns the id of the row the user last chose (or None)."""
    res = _ROWPICK(data=dict(html=table_html, selected=selected_id), key=key, on_row_change=lambda: None,
                   width='stretch', height='content')
    return res.get('row') if hasattr(res, 'get') else None


# ------------------------------------------------------------------------------------------
# Sky map + compass pointing to a target (meteor radiant or comet).
_SKY = st.components.v2.component(
    'afterglow_skypointer',
    js=_read('skypointer.js'),
    css=_read('planner.css') + '\n' + _read('skypointer.css'),
    isolate_styles=False,
)


def show_sky(data, key):
    return _SKY(data=data, key=key, width='stretch', height='content')
