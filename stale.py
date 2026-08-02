"""One message for a page that cannot import what it needs.

Streamlit Community Cloud syncs new code into the Python process that is
already running instead of restarting it. Page scripts are re-read from
disk on every rerun, but imported modules are not: they stay in
sys.modules from the previous build. So a page from the new commit can end
up importing a module left over from the old one, and the import fails for
a name that is plainly right there in the repository.

That mixed state is impossible from any single commit, which is the tell.
It is a deploy state, not a bug in the code, and the only fix is a reboot.
Without this the reader gets a raw ImportError and starts looking for a
missing push.

Deliberately tiny, and deliberately not edited once it works: it is the
handler that exists because imports go stale, so the less it contains the
less of it can be stale.
"""

import streamlit as st

MESSAGE = (
    "**This page is running against an older build of the app.**\n\n"
    "`{error}`\n\n"
    "The server is in a mixed state: a page from the current commit is "
    "importing a module the previous build left loaded. Nothing is wrong "
    "with the code, and rerunning will not clear it.\n\n"
    "**Reboot the app to fix it** - *Manage app* at the bottom right, then "
    "the three-dot menu, then *Reboot app*. Rerun re-runs the page in the "
    "same process and Clear cache only drops cached values; neither "
    "reloads the modules."
)


def guard(error) -> None:
    """Show the message and stop the page. Never returns."""
    st.error(MESSAGE.format(error=error))
    st.stop()
