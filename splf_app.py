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

@st.cache_data(ttl=1800)
def fetch_live_data():
    headers = {"X-Auth-Token": API_KEY}
    url_standings = "https://api.football-data.org/v4/competitions/PL/standings"
    res_standings = requests.get(url_standings, headers=headers)
    url_matches = "https://api.football-data.org/v4/competitions/PL/matches"
    res_matches = requests.get(url_matches, headers=headers)
    
    if res_standings.status_code != 200:
        return None, None
    return res_standings.json(), res_matches.json()

def load_local_files():
    try:
        assignments = pd.read_csv("data/team_assignments.csv")
    except FileNotFoundError:
        st.error("CRITICAL ERROR: Could not find 'data/team_assignments.csv'.")
        return None, None
    
    try:
        # Load the RAW history database (Season, Owner, Team, Rank, Pts, etc.)
        history_raw = pd.read_csv("data/SPLF - HistTables.csv")
    except FileNotFoundError:
        history_raw = pd.DataFrame() 
        
    return assignments, history_raw

def calculate_historical_stats(raw_df):
    """
    Turns raw season logs into the 'Purple Table' Summary.
    Required Columns in CSV: Season, Owner, Team, Rank, Pts, W, D, L, GD
    """
    if raw_df.empty: return pd.DataFrame()

    # 1. Basic Aggregates
    summary = raw_df.groupby("Owner").agg({
        'Pts': 'sum',
        'W': 'sum',
        'D': 'sum',
        'L': 'sum',
        'GD': 'sum'
    })

    # 2. Calculate Historical Money (Per Season Logic)
    season_stats = raw_df.groupby(['Season', 'Owner'])['Pts'].sum().reset_index()
    
    # Calculate Quota per season
    season_totals = season_stats.groupby('Season')['Pts'].sum().reset_index()
    season_totals = season_totals.rename(columns={'Pts': 'Season_Total'})
    
    # Merge totals back to calculate quota
    season_stats = pd.merge(season_stats, season_totals, on='Season')
    season_stats['Quota'] = season_stats['Season_Total'] / 5
    season_stats['Money'] = (season_stats['Pts'] - season_stats['Quota']) * 10
    
    # Sum Money to Summary
    summary['Money'] = season_stats.groupby('Owner')['Money'].sum()

    # 3. Team Medals (1st=4, 2nd=3, 3rd=2, 4th=1)
    raw_df['Team_Medals'] = 0
    raw_df.loc[raw_df['Rank'] == 1, 'Team_Medals'] = 4
    raw_df.loc[raw_df['Rank'] == 2, 'Team_Medals'] = 3
    raw_df.loc[raw_df['Rank'] == 3, 'Team_Medals'] = 2
    raw_df.loc[raw_df['Rank'] == 4, 'Team_Medals'] = 1
    
    summary['Team Medals'] = raw_df.groupby('Owner')['Team_Medals'].sum()

    # 4. Relegations (Rank 18, 19, 20)
    raw_df['Relegated'] = raw_df['Rank'].apply(lambda x: 1 if x >= 18 else 0)
    summary['Teams Relagated'] = raw_df.groupby('Owner')['Relegated'].sum()

    # 5. Player Medals (1st Place in SPLF Season = 5, etc.)
    season_stats['Rank_In_Season'] = season_stats.groupby('Season')['Pts'].rank(ascending=False, method='min')
    
    def get_player_medals(rank):
        if rank == 1: return 5
        elif rank == 2: return 4
        elif rank == 3: return 3
        elif rank == 4: return 2
        elif rank == 5: return 1
        return 0

    season_stats['Player_Medals'] = season_stats['Rank_In_Season'].apply(get_player_medals)
    summary['Player Medals'] = season_stats.groupby('Owner')['Player_Medals'].sum()

    # 6. Final Formatting & Ranking
    summary = summary.reset_index()
    summary = summary.sort_values("Money", ascending=False).reset_index(drop=True)
    summary.index += 1  # Start rank at 1
    summary.index.name = "Rank"
    summary = summary.reset_index() # Make Rank a column

    return summary

def generate_rivalry_matrix(matches_json, assignments):
    if not matches_json: return pd.DataFrame()
    
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
            
            if home_raw in owner_map and away_raw in owner_map:
                owner_home = owner_map[home_raw]
                owner_away = owner_map[away_raw]
                
                if owner_home == owner_away: continue 

                if owner_home < owner_away:
                    pair = (owner_home, owner_away)
                    res_idx = 0 if m['score']['winner'] == 'HOME_TEAM' else (2 if m['score']['winner'] == 'AWAY_TEAM' else 1)
                else:
                    pair = (owner_away, owner_home)
                    if m['score']['winner'] == 'HOME_TEAM': res_idx = 2
                    elif m['score']['winner'] == 'AWAY_TEAM': res_idx = 0
                    else: res_idx = 1
                
                if pair not in rivalries: rivalries[pair] = [0, 0, 0]
                rivalries[pair][res_idx] += 1

    data = []
    for (p1, p2), record in rivalries.items():
        w1, d, w2 = record
        total = w1 + d + w2
        if total == 0: continue
        
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
assignments, history_raw = load_local_files()

if data_standings and assignments is not None:
    
    # 2. Process Standings
    pl_table = data_standings['standings'][0]['table']
    epl_df = pd.DataFrame(pl_table)
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
    owner_stats = owner_stats.sort_values("Pts", ascending=False).reset_index(drop=True)

    # --- TABS ---
    tab_main, tab_h2h = st.tabs(["📊 League Dashboard", "⚔️ Head-to-Head"])

    with tab_main:
        # SECTION 1: SPLF STANDINGS
        st.header("🏆 The SPLF Table")
        
        display_owner = owner_stats.copy()
        cols_order = ["Owner", "Pts", "Money", "GP", "W", "D", "L", "GD"]
        
        st.dataframe(
            display_owner,
            use_container_width=True,
            hide_index=True,
            column_order=cols_order,
            height=250, 
            column_config={
                "Money": st.column_config.NumberColumn("Money", format="$%.2f"),
                "Pts": st.column_config.NumberColumn("Pts", format="%d"),
                "GD": st.column_config.NumberColumn("GD", format="%d")
            }
        )

        st.divider()

        # SECTION 2: REAL EPL TABLE
        st.header("🌍 Real EPL Standings (By Owner)")
        merged_df = merged_df.sort_values(["Pts", "GD"], ascending=False)
        st.dataframe(
            merged_df,
            use_container_width=True,
            hide_index=True,
            column_order=["Team", "Owner", "Pts", "GP", "W", "D", "L", "GD"],
            height=740
        )

        st.divider()

        # SECTION 3: AUTOMATED HISTORY (Calculated Live)
        st.header("All-Time SPLF Player Stats")
        st.caption("11 seasons - 2014/15 thru 2024/25")

        if not history_raw.empty:
            # RUN THE CALCULATOR
            history_summary = calculate_historical_stats(history_raw)

            # Display exactly like the Purple Table in your screenshot
            st.dataframe(
                history_summary,
                use_container_width=True, 
                hide_index=True,          
                height=250,
                column_order=["Rank", "Owner", "Money", "Pts", "W", "D", "L", "GD", "Team Medals", "Player Medals", "Teams Relagated"],
                column_config={
                    "Rank": st.column_config.NumberColumn("Rank", format="%d"),
                    "Money": st.column_config.NumberColumn("Money", format="$ %d"), # No decimals like screenshot
                    "Player Medals": st.column_config.NumberColumn("Player Medals", format="%d"),
                    "Team Medals": st.column_config.NumberColumn("Team Medals", format="%d"),
                    "Pts": st.column_config.NumberColumn("Pts"),
                }
            )
        else:
            st.warning("History file is empty. Make sure 'data/SPLF - HistTables.csv' contains the raw database.")

    with tab_h2h:
        st.header("⚔️ Rivalry Matrix")
        rivalry_df = generate_rivalry_matrix(data_matches, assignments)
        if not rivalry_df.empty:
            st.dataframe(
                rivalry_df,
                use_container_width=True,
                hide_index=True,
                height=600,
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