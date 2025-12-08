import streamlit as st
import json
from google.oauth2 import service_account
import gspread
import keywords_tool
import wikidata_tool
import filter_tool
import split_tool
from streamlit_option_menu import option_menu

# Initialize app options and authentication flag
apps = {}
authenticated = False
client = None

# Sidebar Header
with st.sidebar:
    st.header("Israeli Internet Archive for Iman")

# Handle credentials upload
if not authenticated:
    with st.sidebar:
        st.subheader("Upload Credentials File")
        credentials_file = st.file_uploader("Please upload your JSON credentials file", type="json")

        if credentials_file is not None:
            try:
                # Define the scope for Google API
                scope = [
                    "https://spreadsheets.google.com/feeds", 
                    "https://www.googleapis.com/auth/spreadsheets", 
                    "https://www.googleapis.com/auth/drive"
                ]

                # Read credentials
                credentials = service_account.Credentials.from_service_account_info(
                    json.loads(credentials_file.read().decode("utf-8")), 
                    scopes=scope
                )

                # Authenticate with Google Sheets
                client = gspread.authorize(credentials)
                st.sidebar.success("Credentials uploaded and authenticated successfully!")
                authenticated = True

            except Exception as e:
                st.sidebar.error(f"Error processing credentials: {e}")

# Display the menu once authenticated
if authenticated:
    # Define apps
    apps = {
        "Keywords Search": keywords_tool.run if callable(keywords_tool.run) else None,        
        "Automatic Filter": filter_tool.run if callable(filter_tool.run) else None,
        "Split URL": split_tool.run if callable(split_tool.run) else None,
        "Wikidata Search": wikidata_tool.run if callable(wikidata_tool.run) else None,
    }
    apps = {k: v for k, v in apps.items() if v}  # Filter out invalid entries

    # Sidebar menu
    with st.sidebar:
        selected_app_name = option_menu(
            "Tools Menu",
            options=list(apps.keys()),
            icons=["search", "filter", "link", "database"],  # Customize icons
            menu_icon="tools",
            default_index=0,
            orientation="vertical"  # Sidebar menu
        )

    # Render the selected app
    app_function = apps[selected_app_name]
    if callable(app_function):
        st.title(selected_app_name)
        app_function(client)  # Pass the client to the app function
    else:
        st.error(f"The app '{selected_app_name}' is not callable.")

# If no credentials are uploaded yet
else:
    st.warning("Please upload the credentials file to access the tools.")
