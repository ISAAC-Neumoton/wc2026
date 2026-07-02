import json
import os
import requests
import pandas as pd
import time

def get_all_tournament_event_ids():
    """Queries the scoreboard using a date range string to gather all historical match IDs from Day 1."""
    # We pass a date range (June 1, 2026 to July 5, 2026) to backfill everything from the opening matchday till now
    url = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard?dates=20260601-20260705&limit=100"
    print("Connecting to the master tournament schedule timeline...")
    try:
        response = requests.get(url)
        if response.status_code == 200:
            events = response.json().get("events", [])
            event_ids = [event.get("id") for event in events if event.get("id")]
            print(f"Success! Identified {len(event_ids)} total played or scheduled fixtures across the date range.")
            return event_ids
    except Exception as e:
        print(f"Error accessing tournament calendar: {e}")
    
    return ["760495"]

def fetch_match_summary(event_id):
    """Fetches the deep summary payload for an individual match ID."""
    url = f"https://site.web.api.espn.com/apis/site/v2/sports/soccer/fifa.world/summary?event={event_id}"
    try:
        response = requests.get(url)
        if response.status_code == 200:
            return response.json()
    except Exception:
        return None
    return None

def parse_team_matches(data, event_id):
    """Extracts overall match parameters and team statistics."""
    header = data.get("header", {})
    competitions = header.get("competitions", [])
    if not competitions:
        return []
    competition = competitions[0]
    match_date = competition.get("date")
    status_type = competition.get("status", {}).get("type", {})
    status = status_type.get("shortDetail", "FT")
    
    # Skip matches that haven't been played yet
    if not status_type.get("completed", False) and status == "PRE":
        return []

    boxscore = data.get("boxscore", {})
    teams = boxscore.get("teams", [])
    
    rows = []
    for team_entry in teams:
        team_info = team_entry.get("team", {})
        statistics = {item["name"]: item["displayValue"] for item in team_entry.get("statistics", [])}
        
        rows.append({
            "MatchID": event_id,
            "MatchDate": match_date,
            "Status": status,
            "TeamID": team_info.get("id"),
            "TeamName": team_info.get("displayName"),
            "TeamAbbreviation": team_info.get("abbreviation"),
            "HomeAway": team_entry.get("homeAway"),
            "PossessionPct": statistics.get("possessionPct", "0"),
            "TotalShots": statistics.get("totalShots", "0"),
            "ShotsOnTarget": statistics.get("shotsOnTarget", "0"),
            "PassesAttempted": statistics.get("totalPasses", "0"),
            "AccuratePasses": statistics.get("accuratePasses", "0"),
            "FoulsCommitted": statistics.get("foulsCommitted", "0"),
            "YellowCards": statistics.get("yellowCards", "0"),
            "RedCards": statistics.get("redCards", "0")
        })
    return rows

def parse_goals_events(data, event_id):
    """Extracts scoring event granular data for the Goals Fact table."""
    header = data.get("header", {})
    competitions = header.get("competitions", [])
    if not competitions:
        return []
    competition = competitions[0]
    details = competition.get("details", [])
    
    rows = []
    for item in details:
        if item.get("scoringPlay") == True:
            clock = item.get("clock", {}).get("displayValue", "0'")
            participants = item.get("participants", [])
            scorer = participants[0].get("athlete", {}).get("displayName", "Unknown") if len(participants) > 0 else "Unknown"
            assist = participants[1].get("athlete", {}).get("displayName", "None") if len(participants) > 1 else "None"
            
            rows.append({
                "MatchID": event_id,
                "TeamID": item.get("team", {}).get("id"),
                "Time": clock,
                "Scorer": scorer,
                "Assist": assist,
                "IsOwnGoal": item.get("ownGoal", False),
                "IsPenalty": item.get("penaltyKick", False)
            })
    return rows

def parse_player_performances(data, event_id):
    """Extracts full box score granular player performance metrics matching the 'statistics' schema."""
    boxscore = data.get("boxscore", {})
    rosters = boxscore.get("rosters", [])
    
    rows = []
    for team_roster in rosters:
        team_id = team_roster.get("team", {}).get("id")
        
        # In your shared JSON, this is accessed as a list under the 'roster' key
        player_list = team_roster.get("roster", [])
        
        for p in player_list:
            athlete = p.get("athlete", {})
            
            # FIXED: ESPN maps player-level metrics to the 'statistics' key, not 'stats'
            stats_list = p.get("statistics", [])
            p_stats = {item["name"]: item["displayValue"] for item in stats_list}
            
            # Ensure we track any player who was on the pitch (Starters + Subbed in)
            if p_stats.get("appearances", "0") == "0" and not p.get("starter", False):
                continue
                
            rows.append({
                "MatchID": event_id,
                "TeamID": team_id,
                "PlayerID": athlete.get("id"),
                "PlayerName": athlete.get("displayName") if athlete.get("displayName") else athlete.get("fullName"),
                "Jersey": p.get("jersey", ""),
                "Position": p.get("position", {}).get("displayName", "SUB"),
                "IsStarter": p.get("starter", False),
                "Goals": p_stats.get("totalGoals", "0"),
                "Assists": p_stats.get("goalAssists", "0"),
                "Shots": p_stats.get("totalShots", "0"),
                "ShotsOnTarget": p_stats.get("shotsOnTarget", "0"),
                "FoulsCommitted": p_stats.get("foulsCommitted", "0"),
                "FoulsSuffered": p_stats.get("foulsSuffered", "0"),
                "YellowCards": p_stats.get("yellowCards", "0"),
                "RedCards": p_stats.get("redCards", "0"),
                "Saves": p_stats.get("saves", "0")
            })
    return rows

def main():
    match_list = get_all_tournament_event_ids()
    
    all_fixtures = []
    all_goals = []
    all_players = []
    
    print("\nRunning complete historical backfill processing loop...")
    for idx, m_id in enumerate(match_list, 1):
        print(f"[{idx}/{len(match_list)}] Querying Match ID: {m_id}")
        payload = fetch_match_summary(m_id)
        
        if not payload:
            continue
            
        all_fixtures.extend(parse_team_matches(payload, m_id))
        all_goals.extend(parse_goals_events(payload, m_id))
        all_players.extend(parse_player_performances(payload, m_id))
        
        # Short pause to prevent API rate limiting
        time.sleep(0.3)
        
    # Convert arrays to DataFrames
    df_fixtures = pd.DataFrame(all_fixtures)
    df_goals = pd.DataFrame(all_goals)
    df_players = pd.DataFrame(all_players)
    
    # Export datasets
    os.makedirs("data_output", exist_ok=True)
    if not df_fixtures.empty: df_fixtures.to_csv("data_output/team_matches.csv", index=False)
    if not df_goals.empty: df_goals.to_csv("data_output/goals.csv", index=False)
    if not df_players.empty: df_players.to_csv("data_output/player_stats.csv", index=False)
    
    print("\n--- History Extract Complete! ---")
    print(f"Stored {len(all_fixtures)} Match Performance Records.")
    print(f"Stored {len(all_goals)} Scored Goal Event Records.")
    print(f"Stored {len(all_players)} Individual Player Rows.")

if __name__ == "__main__":
    main()