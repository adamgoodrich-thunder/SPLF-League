import streamlit as st
import pandas as pd
import requests

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
    
    # 1. Standings
    url_standings = "https://api.football-data.org/v4/competitions/PL/standings"
    res_standings = requests.get(url_standings, headers=headers)
    
    # 2. Matches
    url_matches = "https://api.football-data.org/v4/competitions/PL/matches"
    res_matches = requests.get(url_matches, headers=headers)
    
    if res_standings.status_code != 200:
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
        history_file = pd.read_csv("data/SPLF - HistTables.csv")
    except FileNotFoundError:
        history_file = pd.DataFrame() 
        
    return assignments, history_file

def generate_rivalry_matrix(matches_json, assignments):
    """Calculates aggregate records for every owner vs owner matchup"""
    if not matches_json: return pd.DataFrame()
    
    # Map teams to owners (normalizing names)
    owner_map = {}
    for team, owner in zip(assignments['Team'], assignments['Owner']):
        owner_map[team] = owner
        owner_map[team + ' FC'] = owner
        owner_map[team + ' AFC'] = owner

    matches = matches_json['matches']
    rivalries = {} 

    for m in matches:
        if m['status'] == 'FINISHED':
            home_raw = m['homeTeam']['name']
            away_raw = m['awayTeam']['name']
            
            # Check if both teams are owned
            if home_raw in owner_map and away_raw in owner_map:
                owner_home = owner_map[home_raw]
                owner_away = owner_map[away_raw]
                
                if owner_home == owner_away: continue 

                # Sort names alphabetically 
                if owner_home < owner_away:
                    pair = (owner_home, owner_away)
                    # 0=HomeWin(Owner1), 1=Draw, 2=AwayWin(Owner2)
                    res_idx = 0 if m['score']['winner'] == 'HOME_TEAM' else (2 if m['score']['winner'] == 'AWAY_TEAM' else 1)
                else:
                    pair = (owner_away, owner_home)
                    # Flip the result because we flipped the names
                    if m['score']['winner'] == 'HOME_TEAM': res_idx = 2
                    elif m['score']['winner'] == 'AWAY_TEAM': res_idx = 0
                    else: res_idx = 1
                
                if pair not in rivalries: rivalries[pair] = [0, 0, 0]
                rivalries[pair][res_idx] += 1

    # Convert to DataFrame
    data = []
    for (p1, p2), record in rivalries.items():
        w1, d, w2 = record
        total = w1 + d + w2
        if total == 0: continue
        
        # Calculate Win % for the dominant player
        if w1 > w2:
            leader = p1
            pct = (w1 / total) * 100
            display_rec = f"{w1}W - {d}D - {w2}L"
        elif w2 > w1:
            leader = p2
            pct = (w2 / total) * 100
            display_rec = f"{w2}W - {d}D - {w1}L"
        else:
            leader = "Tied"
            pct = 50.0
            display_rec = f"{w1}W - {d}D - {w2}L"

        data.append({
            "Matchup": f"{p1} vs {p2}",
            "Leader": leader,
            "Record": display_rec,
            "Total Games": total,
            "Dominance %": pct
        })

    df = pd.DataFrame(data)
    if not df.empty:
        df = df.sort_values("Dominance %", ascending=False)
    return df

# --- MAIN APP ---

st.title("⚽ SPLF Dashboard")

# 1. Get Data
data_standings, data_matches = fetch_live_data()
assignments, history_archive = load_local_files()

if data_standings and assignments is not None:
    
    # 2. Process Standings
    pl_table = data_standings['standings'][0]['table']
    epl_df = pd.DataFrame(pl_table)
    
    # Cleanup Names
    epl_df['Team'] = epl_df['team'].apply(lambda x: x['name'].replace(' FC', '').replace(' AFC', '').strip())
    epl_df = epl_df.rename(columns={'playedGames': 'GP', 'won': 'W', 'draw': 'D', 'lost': 'L', 'goalDifference': 'GD', 'points': 'Pts'})
    epl_df = epl_df[['Team', 'Pts', 'GP', 'W', 'D', 'L', 'GD']]
    
    # 3. Merge with your Draft
    merged_df = pd.merge(assignments, epl_df, on="Team", how="left").fillna(0)

    # 4. Calculate Scores
    owner_stats = merged_df.groupby("Owner").agg({
        'Pts': 'sum',
        'GP': 'sum',
        'W': 'sum',
        'D': 'sum',
        'L': 'sum',
        'GD': 'sum'
    }).reset_index()
    
    # Calculate Money
    total_league_points = owner_stats['Pts'].sum()
    quota = total_league_points / 5
    owner_stats['Money'] = (owner_stats['Pts'] - quota) * 10
    
    # Sort Leaderboard
    owner_stats = owner_stats.sort_values("Pts", ascending=False).reset_index(drop=True)

    # --- TABS FOR MAJOR SECTIONS ---
    tab_main, tab_h2h = st.tabs(["📊 League Dashboard", "⚔️ Head-to-Head"])

    with tab_main:
        # SECTION 1: SPLF STANDINGS
        st.header("🏆 The SPLF Table")
        
        # Display Money format properly
        display_owner = owner_stats.copy()
        display_owner['Money'] = display_owner['Money'].apply(lambda x: f"${x:,.2f}")
        
        st.dataframe(
            display_owner,
            use_container_width=True,
            hide_index=True,
            column_order=["Owner", "Pts", "Money", "GP", "W", "D", "L", "GD"],
            column_config={
                "Pts": st.column_config.NumberColumn("Points", format="%d"),
                "GD": st.column_config.NumberColumn("GD", format="%d")
            }
        )

        st.divider()

        # SECTION 2: REAL EPL TABLE (With Owners)
        st.header("🌍 Real EPL Standings (By Owner)")
        st.caption("The actual Premier League table, tagged with SPLF Owners.")
        
        # Sort by real EPL points
        merged_df = merged_df.sort_values(["Pts", "GD"], ascending=False)
        
        st.dataframe(
            merged_df,
            use_container_width=True,
            hide_index=True,
            column_order=["Team", "Owner", "Pts", "GP", "W", "D", "L", "GD"]
        )

        st.divider()

        # SECTION 3: HISTORY
        st.header("📜 League History")
        st.caption("All-time historical performance.")

        if not history_archive.empty:
            if 'Year' in history_archive.columns:
                history_archive['Year'] = history_archive['Year'].astype(str).str.replace(',', '')

            st.dataframe(
                history_archive,
                use_container_width=True, 
                hide_index=True,          
                height=500                
            )
        else:
            st.warning("No history file found.")

    with tab_h2h:
        st.header("⚔️ Rivalry Matrix")
        st.caption("Cumulative Head-to-Head records for the current season.")
        
        rivalry_df = generate_rivalry_matrix(data_matches, assignments)
        
        if not rivalry_df.empty:
            st.dataframe(
                rivalry_df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Dominance %": st.column_config.ProgressColumn(
                        "Dominance",
                        format="%.0f%%",
                        min_value=0,
                        max_value=100,
                    ),
                }
            )
        else:
            st.info("No head-to-head matches played yet.")