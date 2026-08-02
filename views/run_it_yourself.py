"""Placeholder: choose parameters and see a result."""

import streamlit as st

try:
    from webdata import coming_soon
except ImportError as error:
    from stale import guard

    guard(error)

st.title("Run it yourself")
coming_soon("pick a position width, fee rate and rebalance cost, and see "
            "the result")
