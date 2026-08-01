"""DLMM backtest results, as a web app.

The entry point: page config and navigation only. Each page lives in
views/ and reads precomputed values through webdata.py -- running the
engine on a page load would mean tens of seconds of work per request, so
nothing here ever calls it.

    streamlit run app.py
"""

import streamlit as st

st.set_page_config(page_title="DLMM Backtest", layout="wide")

PAGES = [
    st.Page("views/results.py", title="Results", default=True),
    st.Page("views/how_it_works.py", title="How it works"),
    st.Page("views/run_it_yourself.py", title="Run it yourself"),
    st.Page("views/run_history.py", title="Run history"),
]

st.navigation(PAGES).run()
