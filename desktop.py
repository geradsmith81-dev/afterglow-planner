"""Desktop-only behaviour for Afterglow.

Covers where this computer keeps Afterglow's data, the Quit button, the automatic shutdown when the
app window is closed, the password used when the app is shared on the local network, and clearing
stored data.

Everything here is switched off on the hosted (GitHub / Streamlit Community Cloud) copy, because
only tools/launch.py sets AFTERGLOW_DESKTOP=1.
"""
import hmac
import ipaddress
import json
import logging
import os
import shutil
import threading
import time

APP = 'Afterglow'
PREFIX = 'AFTERGLOW'
log = logging.getLogger('afterglow.desktop')


# ------------------------------------------------------------------------------------------
# where things are
# ------------------------------------------------------------------------------------------
def is_desktop():
    return os.environ.get(PREFIX + '_DESKTOP') == '1'


def data_dir():
    """Per-user data folder: %LOCALAPPDATA%\\Afterglow (stored data, logs, the running-server note)."""
    base = os.environ.get('LOCALAPPDATA') or os.path.join(os.path.expanduser('~'), 'AppData', 'Local')
    return os.path.join(base, 'Afterglow')


def state_file():
    return os.path.join(data_dir(), 'server.json')


def share_password():
    return os.environ.get(PREFIX + '_SHARE_PASSWORD') or ''


def is_sharing():
    return bool(share_password())


def client_is_local(st):
    """True when the person using this page is sitting at this computer.

    When the app is not shared, the server only listens on this computer, so every visitor is
    local. When it is shared, only a loopback address counts as local; an unknown address does not.
    """
    if not is_sharing():
        return True
    try:
        ip = st.context.ip_address
    except Exception:
        ip = None
    if not ip:
        return False
    try:
        return ipaddress.ip_address(ip.split('%')[0]).is_loopback
    except ValueError:
        return ip == 'localhost'


# ------------------------------------------------------------------------------------------
# password gate (network sharing only)
# ------------------------------------------------------------------------------------------
def require_password(st):
    """Ask visitors from other devices for the sharing password; stop the page until it is given."""
    pw = share_password()
    if not pw or client_is_local(st) or st.session_state.get('_dk_auth'):
        return
    st.markdown('### Afterglow is shared from another computer')
    st.write('Enter the password shown in the Afterglow window on that computer.')
    with st.form('dk_pw', clear_on_submit=True):
        given = st.text_input('Password', type='password')
        ok = st.form_submit_button('Open Afterglow')
    if ok:
        if hmac.compare_digest(given.strip().lower().encode('utf-8'), pw.lower().encode('utf-8')):
            st.session_state['_dk_auth'] = True
            st.rerun()
        time.sleep(1.5)      # slows down guessing
        st.error('That password is not right.')
    st.stop()


# ------------------------------------------------------------------------------------------
# stopping the app
# ------------------------------------------------------------------------------------------
def shutdown(reason, code=0):
    """Stop the whole Afterglow server process."""
    log.info('Stopping Afterglow: %s', reason)
    try:
        with open(state_file(), encoding='utf-8') as f:
            mine = json.load(f).get('pid') == os.getpid()
        if mine:
            os.remove(state_file())
    except Exception:
        pass
    for h in logging.getLogger().handlers:
        try:
            h.flush()
        except Exception:
            pass
    os._exit(code)


def _active_sessions():
    """Number of open app windows, or None while Streamlit is still starting up."""
    from streamlit.runtime import Runtime
    if not Runtime.exists():
        return None
    mgr = getattr(Runtime.instance(), '_session_mgr', None)   # set a moment after the runtime exists
    if mgr is None:
        return None
    return mgr.num_active_sessions()


def start_idle_watch(idle_s=90, first_s=600, poll_s=5):
    """Stop the server once the app window has been closed.

    Counts polls rather than clock time, so a computer waking from sleep is not mistaken for a
    long idle spell: the browser gets idle_s seconds of running time to reconnect.
    """
    need = max(1, int(round(idle_s / poll_s)))
    first_polls = max(1, int(round(first_s / poll_s)))

    def run():
        seen = False
        empty = 0
        waited = 0
        failures = 0
        while True:
            time.sleep(poll_s)
            try:
                n = _active_sessions()
                failures = 0
            except Exception:
                failures += 1
                if failures >= 12:
                    log.exception('Automatic shutdown is off: cannot count open app windows')
                    return
                continue
            if n is None:
                continue
            if n > 0:
                seen, empty = True, 0
                continue
            if not seen:
                waited += 1
                if waited >= first_polls:
                    shutdown('no app window was opened within %d seconds' % first_s)
                continue
            empty += 1
            if empty >= need:
                shutdown('the app window was closed')

    threading.Thread(target=run, name='afterglow-idle-watch', daemon=True).start()


def _quit_now():
    shutdown('Quit button')


# ------------------------------------------------------------------------------------------
# stored data
# ------------------------------------------------------------------------------------------
def _folder_size(path):
    n = b = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                b += os.path.getsize(os.path.join(root, f))
                n += 1
            except OSError:
                pass
    return n, b


def clear_folders(paths):
    """Delete the contents of the given folders. Returns (files removed, bytes removed)."""
    n_all = b_all = 0
    for p in paths:
        if not p or not os.path.isdir(p):
            continue
        n, b = _folder_size(p)
        shutil.rmtree(p, ignore_errors=True)
        os.makedirs(p, exist_ok=True)
        n_all += n
        b_all += b
    return n_all, b_all


def cache_dirs():
    """The stored-data folders the launcher set up for this run (empty on the hosted copy)."""
    raw = os.environ.get(PREFIX + '_CLEAR_DIRS', '')
    return [p for p in raw.split(os.pathsep) if p]


# ------------------------------------------------------------------------------------------
# the controls shown at the bottom of the page on the desktop copy
# ------------------------------------------------------------------------------------------
CLEAR_TITLE = 'stored elevation tiles and downloaded sky data'
CLEAR_TEXT = 'Elevation tiles and downloaded sky data (such as comet orbits) are kept on this computer so that the next look at the same place is faster. The tiles also show which places have been looked up. Clear them before you lend or hand on this computer.'


def desktop_controls(st, on_cleared=None):
    if not is_desktop() or not client_is_local(st):
        return
    dirs = cache_dirs()
    title = 'This computer: stored data and quitting' if dirs else 'This computer: quitting Afterglow'
    with st.expander(title):
        if dirs:
            st.caption(CLEAR_TEXT)
            sure = st.checkbox('Yes, delete the ' + CLEAR_TITLE, key='dk_clear_sure')
            if st.button('Clear stored data', key='dk_clear', disabled=not sure):
                n, b = clear_folders(dirs)
                if on_cleared:
                    on_cleared()
                st.success(f'Removed {n:,} stored files ({b / 1e6:,.1f} MB).')
        st.caption(f"Afterglow's data folder on this computer: {data_dir()}")
        if is_sharing():
            st.caption('Afterglow is shared on this network. Close the Afterglow window with the password '
                       'to stop sharing.')
        if st.button('Quit Afterglow', key='dk_quit', type='primary'):
            st.info('Afterglow has stopped. You can close this window.')
            st.html('<script>setTimeout(function(){try{window.close()}catch(e){}}, 400)</script>',
                    unsafe_allow_javascript=True)
            threading.Timer(1.0, _quit_now).start()
