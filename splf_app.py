import streamlit as st
import pandas as pd
import requests
import plotly.express as px
from datetime import datetime
import os

# --- PAGE SETUP ---
st.set_page_config(page_title="SPLF Live", layout="wide", page_icon="⚽")

# --- LOAD SECRETS ---
try:
    API_KEY = st.secrets["api_key"]
except FileNotFoundError:
    st.error("Secrets file not found. Make sure .streamlit/secrets.toml exists.")
    st.stop()

# --- FUNCTIONS ---

@st.cache_data(ttl=1800) # Update data every 30 minutes
def fetch_live_data():
    """Fetches live 2025/2026 PL Standings and Matches"""
    headers = {"X-Auth-Token": API_KEY}
    
    # 1. Standings (The Table)
    url_standings = "https://api.football-data.org/v4/competitions/PL/standings"
    res_standings = requests.get(url_standings, headers=headers)
    
    # 2. Matches (For Head-to-Head)
    url_matches = "https://api.football-data.org/v4/competitions/PL/matches"
    res_matches = requests.get(url_matches, headers=headers)
    
    if res_standings.status_code != 200:
        st.error(f"API Error {res_standings.status_code}: Could not fetch standings.")
        return None, None
        
    return res_standings.json(), res_matches.json()

def load_local_files():
    """Loads your manual roster and your 11-year history"""
    try:
        assignments = pd.read_csv("data/team_assignments.csv")
    except FileNotFoundError:
        st.error("CRITICAL ERROR: Could not find 'data/team_assignments.csv'.")
        return None, None
        
    try:
        # We try to load the history file you uploaded
        history_file = pd.read_csv("data/SPLF - HistTables.csv")
    except FileNotFoundError:
        history_file = pd.DataFrame() # It's okay if missing, just return empty
        
    return assignments, history_file

def calculate_h2h(matches_json, assignments):
    """Calculates Head-to-Head records"""
    if not matches_json: return pd.DataFrame()
    
    # Create a helper dict to normalize names (remove ' FC', etc)
    team_map = {}
    for team in assignments['Team']:
        team_map[team] = team # Exact match
        team_map[team + ' FC'] = team # Handle "Arsenal FC" vs "Arsenal"
        team_map[team + ' AFC'] = team 

    # Map the cleaned names to owners
    owner_map = {}
    for team, owner in zip(assignments['Team'], assignments['Owner']):
        owner_map[team] = owner
        owner_map[team + ' FC'] = owner
        owner_map[team + ' AFC'] = owner

    matches = matches_json['matches']
    records = []
    
    for m in matches:
        if m['status'] == 'FINISHED':
            home_raw = m['homeTeam']['name']
            away_raw = m['awayTeam']['name']
            
            # Check if these teams belong to our owners
            if home_raw in owner_map and away_raw in owner_map:
                home_owner = owner_map[home_raw]
                away_owner = owner_map[away_raw]
                
                winner = 'Draw'
                if m['score']['winner'] == 'HOME_TEAM': winner = home_owner
                elif m['score']['winner'] == 'AWAY_TEAM': winner = away_owner
                
                records.append({
                    'Home': home_raw,
                    'Away': away_raw,
                    'Home Owner': home_owner,
                    'Away Owner': away_owner,
                    'Winner': winner,
                    'Date': m['utcDate'][:10]
                })
    return pd.DataFrame(records)

# --- MAIN APP ---

st.title("⚽ SPLF Live Dashboard")

# 1. Get Data
data_standings, data_matches = fetch_live_data()
assignments, history_archive = load_local_files()

if data_standings and assignments is not None:
    
    # 2. Process Standings
    pl_table = data_standings['standings'][0]['table']
    
    # create a dataframe of the real EPL table
    epl_df = pd.DataFrame(pl_table)
    
    # --- FIX 1: Normalize Team Names ---
    # The API returns "Arsenal FC", your CSV says "Arsenal". We clean this up.
    epl_df['Team'] = epl_df['team'].apply(lambda x: x['name'].replace(' FC', '').replace(' AFC', '').strip())
    
    # --- FIX 2: Rename 'playedGames' to 'played' ---
    epl_df = epl_df.rename(columns={'playedGames': 'played'})
    
    # Select only what we need
    epl_df = epl_df[['Team', 'points', 'played', 'won', 'draw', 'lost', 'goalDifference']]
    
    # 3. Merge with your Draft
    merged_df = pd.merge(assignments, epl_df, on="Team", how="left")
    
    # CHECK FOR MISSING TEAMS
    missing_teams = merged_df[merged_df['points'].isnull()]
    if not missing_teams.empty:
        st.warning(f"⚠️ Mismatch Warning: The app can't find these teams in the live API: {missing_teams['Team'].tolist()}. Check the spelling in your CSV.")
        merged_df = merged_df.fillna(0)

    # 4. Calculate Scores
    owner_stats = merged_df.groupby("Owner").agg({
        'points': 'sum',
        'played': 'sum',
        'won': 'sum',
        'draw': 'sum',
        'lost': 'sum',
        'goalDifference': 'sum'
    }).reset_index()
    
    # Calculate Money
    total_league_points = owner_stats['points'].sum()
    quota = total_league_points / 5
    owner_stats['Money'] = (owner_stats['points'] - quota) * 10
    
    # Sort Leaderboard
    owner_stats = owner_stats.sort_values("points", ascending=False).reset_index(drop=True)

    # --- DISPLAY DASHBOARD ---
    
    # Top Metrics
    c1, c2, c3 = st.columns(3)
    if not owner_stats.empty:
        leader = owner_stats.iloc[0]
        c1.metric("Current Leader", f"{leader['Owner']}", f"{int(leader['points'])} pts")
        c2.metric("The Quota", f"{quota:.1f} pts", "Break-even Line")
        c3.metric("Projected Winner", f"{leader['Owner']}", f"Proj: ${leader['Money']:.2f}")

    # Tabs
    tab1, tab2, tab3 = st.tabs(["💰 The Money Table", "⚔️ Head-to-Head", "🏛️ Hall of Fame"])
    
    with tab1:
        st.subheader("Live Standings")
        display_df = owner_stats.copy()
        display_df['Money'] = display_df['Money'].apply(lambda x: f"${x:,.2f}")
        
        st.dataframe(
            display_df[['Owner', 'points', 'Money', 'played', 'won', 'goalDifference']],
            use_container_width=True,
            hide_index=True,
            column_config={
                "points": st.column_config.NumberColumn("Points", format="%d"),
                "goalDifference": st.column_config.NumberColumn("GD", format="%d")
            }
        )
        
        with st.expander("See Team-by-Team Breakdown"):
            st.dataframe(merged_df.sort_values(['Owner', 'points'], ascending=[True, False]), use_container_width=True)

    with tab2:
        st.subheader("Head-to-Head Records")
        h2h_df = calculate_h2h(data_matches, assignments)
        
        if not h2h_df.empty:
            selected_owner = st.selectbox("Select Manager", owner_stats['Owner'].unique())
            
            # Filter for games involving this owner
            my_games = h2h_df[ (h2h_df['Home Owner'] == selected_owner) | (h2h_df['Away Owner'] == selected_owner) ]
            
            # Calculate Record
            wins = len(my_games[my_games['Winner'] == selected_owner])
            draws = len(my_games[my_games['Winner'] == 'Draw'])
            losses = len(my_games) - wins - draws
            
            st.write(f"### {selected_owner}'s Record: {wins}W - {draws}D - {losses}L")
            st.dataframe(my_games, hide_index=True, use_container_width=True)
        else:
            st.info("No head-to-head matches have been played yet.")

    with tab3:
        st.subheader("League History (2015-2025)")
        if not history_archive.empty:
            st.dataframe(history_archive, use_container_width=True)
        else:
            st.warning("No history file found in 'data/SPLF - HistTables.csv'")