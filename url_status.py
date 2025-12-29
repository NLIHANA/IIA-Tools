import streamlit as st
import pandas as pd
from searching import domain_split

def run(client):
    # Main interface for URL filtering
    st.write(
        "This tool processes a list of URLs and checks their activity status. The results are saved [here](https://docs.google.com/spreadsheets/d/1Fz3mn49yd-cX5QeFekHNZj-8D58UQ6aJMJKCxklpupA/)."
    )
