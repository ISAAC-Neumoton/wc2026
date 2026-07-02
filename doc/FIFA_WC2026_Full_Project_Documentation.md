# FIFA World Cup 2026 Live Dashboard — Project Documentation (v2)

**Owner:** Isaac | **Tools:** API-Football, Python, Windows Task Scheduler, Power Query (M), Power BI Desktop + Service | **Output:** Live public dashboard + daily content series

This replaces the earlier version. Two things changed: the pipeline is now **local-first** (your laptop does the work, cloud is only used for the one step that genuinely requires it), and the build order now starts with **verifying real data** before writing any automation or report logic.

---

## How This Project Flows

```
Your laptop:
  Python script → writes a CSV into your OneDrive folder
        │
        ▼
  Windows Task Scheduler → runs that script automatically, once a day
        │
        ▼
  Power BI Desktop → Power Query reads the OneDrive CSV → cleans it → builds the model
        │
        ▼
  Publish to Power BI Service  ← the only step that needs the cloud
        │
        ▼
  Power BI Service → scheduled refresh, reading the same OneDrive file
        │
        ▼
  Public link — stays live and updates daily, even if your laptop is off
        │
        ▼
  Daily post — one stat, one question, one link → LinkedIn/X, building followers
```

Everything except the "Publish" step runs entirely on your machine. No GitHub Actions, no Google Sheets, no external server — OneDrive is the one shared folder both your script and Power BI Service can see.

---

## Phase 0 — Verify Before You Build Anything

Do this first, before writing a single line of pipeline code or opening Power BI:

**1. Check API coverage for the competition.**

```
GET https://v3.football.api-sports.io/leagues?id=1&season=2026
```

Look at the `coverage` object and confirm these flags:

| Flag | If true | If false |
|---|---|---|
| `fixtures.events` | Goals/assists/cards work as planned | Player Statistics needs manual tracking |
| `fixtures.statistics_players` | Saves, shots, ratings all work | Saves won't be available; assists may still work via events |
| `top_scorers` / `top_assists` / `top_cards` | Use these endpoints directly | Build leaderboards yourself from raw events |
| `standings` | Standings page fully automated | Build standings yourself from match results |

API-Football's own docs note that a `true` flag doesn't guarantee 100% data availability — so also do step 2.

**2. Pull one real sample by hand.**

Call `/fixtures`, `/fixtures/events`, and `/fixtures/players` for a single finished match (use any recent international fixture if the World Cup hasn't started yet). Save the raw JSON. This confirms, concretely:

- Whether `assist` is actually populated on goal events, not just present as a field
- What `position` values look like for goalkeepers (so you can filter correctly for saves)
- Whether own goals are flagged in `detail`, and how
- The exact shape of `fixtures/players` statistics you'll be parsing

**3. Turn that one sample into a small static CSV.**

Hand-flatten it, or run a stripped-down version of the Python script against just that one fixture ID. This becomes your development data — stable, doesn't cost API calls, doesn't change while you're mid-build.

Only once these three are done do you move to Phase 1.

---

## Phase 1 — Data Getting

### 1.1 Source

**API-Football** (api-sports.io / RapidAPI). Free tier: 100 requests/day. World Cup coverage (`league=1`, `season=2026`) includes fixtures, live scores, standings, goal events, cards, and per-player match stats — confirmed available *in general*; confirmed *for this competition specifically* is what Phase 0 checked.

### 1.2 Endpoints

| Endpoint | What it gives you | Call frequency |
|---|---|---|
| `/fixtures?league=1&season=2026` | Full schedule, live scores, status | 1x/day |
| `/fixtures/events?fixture=ID` | Goals (with `assist`), cards, subs, per match | Once per finished fixture |
| `/fixtures/players?fixture=ID` | Full player match stats: shots, passes, saves, rating | Once per finished fixture |
| `/standings?league=1&season=2026` | All 12 group tables | 1x/day |

### 1.3 Python script — writes to OneDrive, not Google Sheets

```python
import requests, csv, os
from pathlib import Path

API_KEY = os.environ["API_FOOTBALL_KEY"]
HEADERS = {"x-apisports-key": API_KEY}
BASE = "https://v3.football.api-sports.io"

# Point this at your OneDrive-synced folder
OUTPUT_DIR = Path.home() / "OneDrive" / "WC2026"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

def get(endpoint, params):
    r = requests.get(f"{BASE}/{endpoint}", params=params, headers=HEADERS)
    r.raise_for_status()
    return r.json()["response"]

fixtures = get("fixtures", {"league": 1, "season": 2026, "status": "FT"})

goal_rows, card_rows, player_rows = [], [], []

for f in fixtures:
    fid = f["fixture"]["id"]
    match_date = f["fixture"]["date"]

    for e in get("fixtures/events", {"fixture": fid}):
        base = {"fixture_id": fid, "date": match_date, "team": e["team"]["name"],
                 "player": e["player"]["name"] if e["player"] else None,
                 "minute": e["time"]["elapsed"], "detail": e["detail"]}
        if e["type"] == "Goal":
            base["assist"] = e["assist"]["name"] if e.get("assist") else None
            goal_rows.append(base)
        elif e["type"] == "Card":
            card_rows.append(base)

    for team_block in get("fixtures/players", {"fixture": fid}):
        team_name = team_block["team"]["name"]
        for p in team_block["players"]:
            s = p["statistics"][0]
            player_rows.append({
                "fixture_id": fid, "date": match_date, "team": team_name,
                "player": p["player"]["name"], "position": s["games"]["position"],
                "minutes": s["games"]["minutes"], "rating": s["games"]["rating"],
                "shots_total": s["shots"]["total"], "goals": s["goals"]["total"],
                "assists": s["goals"]["assists"], "saves": s["goals"]["saves"],
                "yellow": s["cards"]["yellow"], "red": s["cards"]["red"],
            })

def write_csv(filename, rows):
    if not rows:
        return
    path = OUTPUT_DIR / filename
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

write_csv("goals.csv", goal_rows)
write_csv("cards.csv", card_rows)
write_csv("player_match_stats.csv", player_rows)
```

Store `API_FOOTBALL_KEY` as a Windows environment variable (Settings → System → About → Advanced system settings → Environment Variables), not hardcoded in the script.

### 1.4 Automating it — Windows Task Scheduler (free, built into Windows)

1. Open **Task Scheduler** → Create Basic Task.
2. Trigger: **Daily**, set a time shortly after most matches finish.
3. Action: **Start a program** → `python.exe`, arguments: the full path to your script.
4. Under the task's **Conditions** tab, uncheck "Start the task only if the computer is on AC power" if you're on a laptop, so it still runs on battery.
5. Test it with **Run** manually once to confirm it writes the CSVs correctly before trusting the schedule.

No repo secrets, no YAML, no cloud account needed for this step.

### 1.5 Fallback for day one

If the script or scheduler isn't working yet, run the script manually whenever you want fresh data, or fill a `player_stats_manual.csv` by hand (`Player, Team, Match Date, Goals, Assists, Saves, Cards`). Power BI doesn't care where the file came from, only that the column names match what you build against.

---

## Phase 2 — Data Cleaning (Power Query / M)

### 2.1 Core cleanup steps

Apply these, in order, to every table you load (Fixtures, Goals, Cards, PlayerMatchStats):

1. **Trim/Clean text columns** — `Text.Trim` + `Text.Clean` on all team/player/ground name fields.
2. **Standardize team names** — build a `TeamNameMap` reference table (raw name → display name, 3-letter code, flag) and merge it into every table with a team column.
3. **Match Status** conditional column: `null` score → `"Upcoming"`; scored + date < today → `"Played"`; date = today → `"Live/Today"`.
4. **Winner** column: compare scores → `team1`, `team2`, or `"Draw"`.
5. **Goal Difference** helper: `score.home − score.away`, signed, per row.
6. **Stage** column from `round`, mapped via a small reference table to `"Group Stage"`, `"Round of 32"`, `"Round of 16"`, `"Quarter-Final"`, `"Semi-Final"`, `"Third Place"`, `"Final"`.
7. **Split date/time** into a proper `Match Date` (date) and `Kickoff Time` (time).
8. **Type-cast everything explicitly** — nothing left as `Any`.

### 2.2 Build the Team-Match table (long format)

1. Duplicate the cleaned Fixtures query → rename `TeamMatches`.
2. `Table.Combine` two transformed copies: one renaming `team1→Team, team2→Opponent, score.home→GoalsFor, score.away→GoalsAgainst`; the other swapped.
3. `Result` column: `GoalsFor > GoalsAgainst → "Win"`, `<` → `"Loss"`, `=` → `"Draw"`.
4. `Points` column: Win=3, Draw=1, Loss=0 (group stage only).

This table drives Standings, Team Statistics, and most of Tournament Insights.

### 2.3 Goals table

1. Load `goals.csv`, type-cast `minute` as whole number, `date` as date.
2. Own goals: if `detail` flags `"Own Goal"`, credit the goal to the **conceding** team via a conditional column.
3. This table plus `PlayerMatchStats` gives Top Scorer, Assist Leaders, and Save Leaders with no manual entry.

### 2.4 Reference / dimension tables

- **Teams** — Name, Code, Group, Flag.
- **Dates** — calendar table, marked as Date table.
- **TeamNameMap** — merge source only, doesn't need to load into the model.

---

## Phase 3 — Dashboard (Power BI)

### 3.1 Data model

**Fact tables:** `Fixtures` (wide), `TeamMatches` (long), `Goals`, `PlayerMatchStats`, `Cards`.
**Dimension tables:** `Teams`, `Dates` (Date table).
**Relationships:** `TeamMatches[Team] → Teams[Name]`, `Goals[Team] → Teams[Name]`, `PlayerMatchStats[Team] → Teams[Name]`, `Fixtures[Match Date] → Dates[Date]`. Keep `Fixtures` and `TeamMatches` unrelated to each other.

### 3.2 Core DAX measures

```dax
Matches Played = CALCULATE(COUNTROWS(Fixtures), Fixtures[Match Status] = "Played")
Total Goals = SUM(Fixtures[score.home]) + SUM(Fixtures[score.away])
Avg Goals per Match = DIVIDE([Total Goals], [Matches Played])

Team Points = SUMX(TeamMatches, TeamMatches[Points])
Team Wins = CALCULATE(COUNTROWS(TeamMatches), TeamMatches[Result] = "Win")
Team Draws = CALCULATE(COUNTROWS(TeamMatches), TeamMatches[Result] = "Draw")
Team Losses = CALCULATE(COUNTROWS(TeamMatches), TeamMatches[Result] = "Loss")
Goals For = SUM(TeamMatches[GoalsFor])
Goals Against = SUM(TeamMatches[GoalsAgainst])
Goal Difference = [Goals For] - [Goals Against]
Win Rate % = DIVIDE([Team Wins], COUNTROWS(TeamMatches))
Clean Sheets = CALCULATE(COUNTROWS(TeamMatches), TeamMatches[GoalsAgainst] = 0)

Days Until Final =
DATEDIFF(TODAY(), CALCULATE(MAX(Fixtures[Match Date]), Fixtures[Stage] = "Final"), DAY)

Top Scorer Goals = CALCULATE(COUNTROWS(Goals), REMOVEFILTERS(Goals[Player]))
Player Goal Rank = RANKX(ALL(Goals[Player]), CALCULATE(COUNTROWS(Goals)))
Assist Leaders = CALCULATE(SUM(PlayerMatchStats[assists]))
Save Leaders = CALCULATE(SUM(PlayerMatchStats[saves]), PlayerMatchStats[position] = "G")
```

### 3.3 Pages — KPIs, visuals, viewer questions

**Page 1 — Standings**
KPIs: Points, Played, W/D/L, GF, GA, GD. Good: Best Attack, Best Defense. Bad: Most Goals Conceded, "Eliminated" flag.
Visuals: matrix per group, conditional formatting, Group slicer.
Question: *"Which team is most likely to finish top of their group after today's results — and which team needs a miracle?"*

**Page 2 — Results**
KPIs: Matches played, Total goals, Avg goals/match. Good: biggest win margin, highest-scoring match. Bad: most one-sided scoreline, longest goalless streak.
Visuals: sortable results table, score-margin bar chart, "shockers" callout.
Question: *"What's been the biggest surprise result of the tournament so far?"*

**Page 3 — Fixtures**
KPIs: Matches remaining, matches today/this week, days to Final. Good: team in form heading into next match. Bad: team on a losing streak heading in.
Visuals: upcoming list by date, countdown card, filters.
Question: *"Which upcoming fixture are you most excited to watch, and who wins it?"*

**Page 4 — Player Statistics**
KPIs (pending Phase 0 confirmation): Top Scorer, Assist Leaders, Save Leaders, Goal+Assist leaderboard. Good: most efficient scorer. Bad: most-carded players, big names yet to score.
Visuals: ranked bar charts, player table with drill-through.
Question: *"Who do you think wins the Golden Boot this World Cup?"*

**Page 5 — Team Statistics**
KPIs: Good: best win rate, most clean sheets, most goals scored, longest unbeaten run. Bad: worst win rate, most conceded, longest winless run.
Visuals: attack-vs-defense quadrant scatter chart, ranked table, 2-team comparison.
Question: *"Which team has looked the most complete (attack + defense) so far?"*

**Page 6 — Knockout Stage**
KPIs: teams remaining by stage, matches decided by penalties, avg goals knockout vs group stage. Good: best knockout goal difference. Bad: narrowest margins/penalty scrapes.
Visuals: bracket visual, stage filter, path-to-final table.
Question: *"Who's your dark horse to make a surprise run in the knockout stage?"*

**Page 7 — Tournament Insights**
KPIs: total goals, avg goals/match, goals by stage. Good: composite "Team of the Tournament" score. Bad: most underwhelming favorite (optional, needs external rankings).
Visuals: headline KPI cards, goals-by-stage bar chart, daily-updated narrative text box.
Question: *"What's one stat from this tournament that's surprised you the most?"*

---

## Phase 4 — Shipping

### 4.1 Publish it live, free, and public

1. Finish the report in Power BI Desktop.
2. **File → Publish → Publish to Power BI**, choose **My Workspace** (free).
3. Creating a public embed code needs a **Pro or PPU** license — start the free 60-day Pro trial if needed.
4. In **app.powerbi.com → My Workspace**, open the report → **File → Embed report → Publish to web (public)** → Create embed code.
5. You get a public URL (share this) and an iframe snippet (for later, on your portfolio site).
6. No login, no row-level security on this link — fine for public World Cup scores, never use this method for sensitive data. Cache refreshes roughly hourly after each data refresh.
7. **Daily refresh:** point Power BI Service's scheduled refresh at the same OneDrive file your script updates. Since it's OneDrive (not a random local path), the Service can read it without needing a gateway installed.

**Backup if Pro trial isn't available:** Tableau Public — fully free, no license tier, built for this exact use case.

### 4.2 Daily posting to build followers

**Format (roughly 80–120 words + one visual):**
1. Hook — one surprising number from today's data
2. Context — why it matters in one sentence
3. The ask — reuse that page's viewer question
4. The link — your live dashboard URL

**Content calendar rotation:**

| Day pattern | Page | Angle |
|---|---|---|
| Matchday +1 | Results | "Yesterday's biggest story" |
| Mid-cycle | Standings | "Who's through, who's on the brink" |
| Mid-cycle | Player Statistics | "Golden Boot race update" |
| Mid-cycle | Team Statistics | "Best attack vs best defense so far" |
| Pre-matchday | Fixtures | "What to watch today/tomorrow" |
| Weekly | Tournament Insights | "The stat that surprised me this week" |
| Knockout phase | Knockout Stage | "Bracket update + dark horse pick" |

**Growth tactics:** post at a consistent time daily; always end with a question; use a screenshot/GIF of the actual dashboard, not just text; occasionally credit the pipeline itself ("automated this from API-Football + Power BI, updates daily on its own"); track which page's posts land best after ~2 weeks and lean into it.

---

## Project Folder Structure

```
fifa-wc2026-dashboard/
│
├── data_pipeline/
│   ├── update_stats.py
│   ├── requirements.txt
│   └── sample_data/              # Phase 0 raw JSON samples, kept for reference
│
├── power_query/
│   └── m_queries_reference.pq    # cleaning steps saved as plain text
│
├── power_bi/
│   └── WC2026_Dashboard.pbix
│
├── docs/
│   └── FIFA_WC2026_Documentation.md
│
└── README.md
```

`API_FOOTBALL_KEY` lives in a Windows environment variable, never in a file inside this folder. If you later push this to GitHub for your portfolio, add a `.gitignore` covering `*.csv` (your data) and any config with keys in it.

---

## Build Order — Start Here, In This Order

1. **Phase 0** — coverage check + one hand-pulled sample + static CSV from it. Don't skip this; every KPI decision downstream depends on knowing what data actually exists.
2. **Power Query, built against the static sample** (Phase 2) — get cleaning logic solid against data that won't shift under you.
3. **Data model + DAX measures** (Phase 3.1–3.2), still against the static sample.
4. **Pages 1, 2, 3, 6** (Standings, Results, Fixtures, Knockout) — fully supported with zero ambiguity, build these first for a working, confident base.
5. **Page 5** (Team Statistics) — fast once Standings exists.
6. **Page 4, then 7** (Player Statistics, Tournament Insights) — last, since they depend on Phase 0's findings and benefit from the other six pages already existing.
7. **Now write the real Python script and wire up Task Scheduler** (Phase 1.3–1.4) — you already know exactly what shape of data the report needs, so this step has no guesswork left.
8. **Swap Power BI's source** from the static sample file to the live OneDrive CSV — same column names, so this should be a small change, not a rebuild.
9. **Publish** (Phase 4.1) — test the public link on your phone, logged out, to confirm a stranger can see it.
10. **First post** (Phase 4.2) — go live the same day you ship.

Ready to start on step 1 whenever you are.