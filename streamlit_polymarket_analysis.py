import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
 
INPUT_FILE = "polymarket_football_all_sources.csv"
 
st.set_page_config(
    page_title="Polymarket Fußball Analyse",
    layout="wide",
    page_icon="⚽",
)
 
# ── Styling ──────────────────────────────────────────────────────────────────
st.markdown("""
<style>
[data-testid="stMetricValue"] { font-size: 1.4rem; font-weight: 600; }
[data-testid="stMetricDelta"] { font-size: 0.85rem; }
</style>
""", unsafe_allow_html=True)
 
st.title("⚽ Polymarket Fußball Strategieanalyse")
st.caption("Simulation: 1 € Einsatz pro Spiel auf Home / Draw / Away / Favorit")
 
# ── Hilfsfunktionen ──────────────────────────────────────────────────────────
 
def calculate_profit(row, bet_type):
    cols   = {"home": "poly_home_odds_5min", "draw": "poly_draw_odds_5min", "away": "poly_away_odds_5min"}
    result = {"home": "H",                   "draw": "D",                   "away": "A"}
    odds   = row[cols[bet_type]]
    if pd.isna(odds):
        return None
    return (odds - 1) if row["result"] == result[bet_type] else -1
 
 
def calculate_favorite_profit(row):
    candidates = {
        "home": row["poly_home_odds_5min"],
        "draw": row["poly_draw_odds_5min"],
        "away": row["poly_away_odds_5min"],
    }
    candidates = {k: v for k, v in candidates.items() if pd.notna(v)}
    if not candidates:
        return None
    fav = min(candidates, key=candidates.get)
    result_map = {"home": "H", "draw": "D", "away": "A"}
    return (candidates[fav] - 1) if row["result"] == result_map[fav] else -1
 
 
def roi(series):
    valid = series.dropna()
    total_bet = len(valid)
    return (valid.sum() / total_bet * 100) if total_bet else 0
 
 
def win_rate(series, df):
    return (series.dropna() > 0).sum() / len(series.dropna()) * 100 if len(series.dropna()) else 0
 
 
# ── Daten laden ───────────────────────────────────────────────────────────────
 
@st.cache_data
def load_data(quality_score_max: int, leagues: list, seasons: list):
    df = pd.read_csv(INPUT_FILE)
 
    required = [
        "result", "poly_home_odds_5min", "poly_draw_odds_5min", "poly_away_odds_5min",
        "mapping_quality_score", "mapping_quality",
    ]
    missing = [c for c in required if c not in df.columns]
    if missing:
        st.error(f"Fehlende Spalten: {missing}")
        st.stop()
 
    # Filter: Qualitätsstufe
    df = df[df["mapping_quality_score"] <= quality_score_max].copy()
 
    # Filter: Liga & Saison
    if "league" in df.columns and leagues:
        df = df[df["league"].isin(leagues)]
    if "season" in df.columns and seasons:
        df = df[df["season"].isin(seasons)]
 
    # Filter: vollständige Odds
    df = df[
        df["poly_home_odds_5min"].notna() &
        df["poly_draw_odds_5min"].notna() &
        df["poly_away_odds_5min"].notna()
    ].copy()
 
    df = df.reset_index(drop=True)
    df["spiel_nr"] = df.index + 1
 
    df["profit_home"]     = df.apply(lambda r: calculate_profit(r, "home"), axis=1)
    df["profit_draw"]     = df.apply(lambda r: calculate_profit(r, "draw"), axis=1)
    df["profit_away"]     = df.apply(lambda r: calculate_profit(r, "away"), axis=1)
    df["profit_favorite"] = df.apply(calculate_favorite_profit, axis=1)
 
    for s in ["home", "draw", "away", "favorite"]:
        col = f"profit_{s}"
        df[f"cum_{col}"]  = df[col].cumsum()
        df[f"avg_{col}"]  = df[col].expanding().mean()
 
    return df
 
 
# ── Sidebar Filter ─────────────────────────────────────────────────────────────
 
raw = pd.read_csv(INPUT_FILE)
 
with st.sidebar:
    st.header("Filter")
 
    # Qualitätsstufe
    quality_max = st.slider(
        "Max. Mapping-Quality-Score",
        min_value=1, max_value=5, value=2,
        help="1–2 = beste Qualität (empfohlen), 5 = alle"
    )
 
    quality_labels = {
        1: "Tier 1 – verifiziert (1x2 oder alle 3 Binär-Märkte + Ergebnis stimmt)",
        2: "Tier 2 – gematcht, Ergebnis fehlt noch (laufende Saison)",
        3: "Tier 3 – nur 2 Binär-Märkte (kein Draw)",
        4: "Tier 4 – Warnstufe (Mismatch oder nur 1 Markt)",
        5: "Tier 5 – kein Markt gefunden",
    }
    st.caption(quality_labels.get(quality_max, ""))
 
    leagues = []
    if "league" in raw.columns:
        all_leagues = sorted(raw["league"].dropna().unique())
        leagues = st.multiselect("Liga", all_leagues, default=all_leagues)
 
    seasons = []
    if "season" in raw.columns:
        all_seasons = sorted(raw["season"].dropna().unique())
        seasons = st.multiselect("Saison", all_seasons, default=all_seasons)
 
    st.divider()
    st.caption("Simulation: 1 € Einsatz pro Spiel")
 
 
df = load_data(quality_max, leagues, seasons)
 
if df.empty:
    st.warning("Keine Spiele mit diesen Filtereinstellungen gefunden.")
    st.stop()
 
n_games = len(df)
 
# ── Qualitäts-Zusammenfassung ──────────────────────────────────────────────────
 
with st.expander("📊 Mapping-Qualität der gefilterten Spiele", expanded=False):
    if "mapping_quality" in df.columns:
        qcounts = df["mapping_quality"].value_counts().reset_index()
        qcounts.columns = ["Qualitätsstufe", "Anzahl"]
        qcounts["Anteil"] = (qcounts["Anzahl"] / n_games * 100).round(1).astype(str) + " %"
        st.dataframe(qcounts, use_container_width=True, hide_index=True)
 
# ── Kennzahlen ────────────────────────────────────────────────────────────────
 
st.subheader(f"Kennzahlen ({n_games} Spiele)")
 
c1, c2, c3, c4 = st.columns(4)
 
strategies = [
    ("Home",    "profit_home",     c1, "🏠"),
    ("Draw",    "profit_draw",     c2, "🤝"),
    ("Away",    "profit_away",     c3, "✈️"),
    ("Favorit", "profit_favorite", c4, "⭐"),
]
 
for label, col, container, icon in strategies:
    total  = df[col].sum()
    avg    = df[col].mean()
    wr     = (df[col].dropna() > 0).sum() / len(df[col].dropna()) * 100
    roi_pct = roi(df[col])
    container.metric(
        f"{icon} {label}",
        f"{total:+.2f} €",
        f"Ø {avg:+.4f} € | ROI {roi_pct:+.1f} % | {wr:.0f} % Treffer"
    )
 
# ── Chart 1: Kumulierter Gewinn ────────────────────────────────────────────────
 
st.subheader("Kumulierter Gewinn über alle Spiele")
 
COLORS = {"Home": "#4A7FD4", "Draw": "#E8A838", "Away": "#4CAF7D", "Favorit": "#E05C5C"}
 
fig1, ax1 = plt.subplots(figsize=(13, 4.5))
fig1.patch.set_facecolor("#0E1117")
ax1.set_facecolor("#0E1117")
 
for label, col, _, _ in strategies:
    series = df[f"cum_{col}"].dropna()
    x = df["spiel_nr"].iloc[:len(series)]
    ax1.plot(x, series, label=label, color=COLORS[label], linewidth=2)
    ax1.fill_between(x, series, alpha=0.08, color=COLORS[label])
 
ax1.axhline(0, color="white", linewidth=0.6, linestyle="--", alpha=0.4)
ax1.set_xlabel("Spielnummer", color="white")
ax1.set_ylabel("Kumulierter Gewinn (€)", color="white")
ax1.tick_params(colors="white")
ax1.spines[:].set_color("#333")
ax1.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.2f €"))
ax1.legend(facecolor="#1A1D23", labelcolor="white", framealpha=0.8)
ax1.grid(axis="y", color="#333", linewidth=0.5)
 
st.pyplot(fig1)
plt.close(fig1)
 
# ── Chart 2: Durchschnittlicher Gewinn pro Spiel (rolling) ────────────────────
 
st.subheader("Durchschnittlicher Gewinn pro Spiel")
 
fig2, ax2 = plt.subplots(figsize=(13, 4))
fig2.patch.set_facecolor("#0E1117")
ax2.set_facecolor("#0E1117")
 
for label, col, _, _ in strategies:
    series = df[f"avg_{col}"].dropna()
    x = df["spiel_nr"].iloc[:len(series)]
    ax2.plot(x, series, label=label, color=COLORS[label], linewidth=1.8)
 
ax2.axhline(0, color="white", linewidth=0.6, linestyle="--", alpha=0.4)
ax2.set_xlabel("Spielnummer", color="white")
ax2.set_ylabel("Ø Gewinn / Spiel (€)", color="white")
ax2.tick_params(colors="white")
ax2.spines[:].set_color("#333")
ax2.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.3f €"))
ax2.legend(facecolor="#1A1D23", labelcolor="white", framealpha=0.8)
ax2.grid(axis="y", color="#333", linewidth=0.5)
 
st.pyplot(fig2)
plt.close(fig2)
 
# ── Chart 3: Endgewinn Balken ──────────────────────────────────────────────────
 
st.subheader("Endgewinn nach allen Spielen")
 
fig3, ax3 = plt.subplots(figsize=(8, 4))
fig3.patch.set_facecolor("#0E1117")
ax3.set_facecolor("#0E1117")
 
labels  = [s[0] for s in strategies]
totals  = [df[s[1]].sum() for s in strategies]
colors  = [COLORS[l] for l in labels]
bars    = ax3.bar(labels, totals, color=colors, width=0.55)
 
for bar, val in zip(bars, totals):
    ypos = val + 0.3 if val >= 0 else val - 0.8
    ax3.text(bar.get_x() + bar.get_width() / 2, ypos, f"{val:+.2f} €",
             ha="center", color="white", fontsize=11, fontweight="bold")
 
ax3.axhline(0, color="white", linewidth=0.6, linestyle="--", alpha=0.4)
ax3.set_ylabel("Gewinn (€)", color="white")
ax3.tick_params(colors="white")
ax3.spines[:].set_color("#333")
ax3.grid(axis="y", color="#333", linewidth=0.5)
 
st.pyplot(fig3)
plt.close(fig3)
 
# ── Chart 4: Odds-Verteilung ───────────────────────────────────────────────────
 
st.subheader("Odds-Verteilung (5 min vor Anstoß)")
 
fig4, axes = plt.subplots(1, 3, figsize=(13, 3.5))
fig4.patch.set_facecolor("#0E1117")
 
for ax, (label, col_prefix, color) in zip(axes, [
    ("Home", "home", COLORS["Home"]),
    ("Draw", "draw", COLORS["Draw"]),
    ("Away", "away", COLORS["Away"]),
]):
    col = f"poly_{col_prefix}_odds_5min"
    data = df[col].dropna()
    ax.set_facecolor("#0E1117")
    ax.hist(data, bins=25, color=color, alpha=0.85, edgecolor="#0E1117")
    ax.axvline(data.median(), color="white", linewidth=1, linestyle="--", alpha=0.6)
    ax.set_title(f"{label} (Median: {data.median():.2f}x)", color="white")
    ax.tick_params(colors="white")
    ax.spines[:].set_color("#333")
    ax.set_xlabel("Quote", color="white")
    ax.set_ylabel("Anzahl Spiele", color="white")
 
fig4.tight_layout()
st.pyplot(fig4)
plt.close(fig4)
 
# ── Chart 5: Gewinnrate pro Liga ───────────────────────────────────────────────
 
if "league" in df.columns and df["league"].nunique() > 1:
    st.subheader("Gewinnrate nach Liga")
 
    liga_stats = []
    for league, grp in df.groupby("league"):
        for label, col, _, _ in strategies:
            valid = grp[col].dropna()
            wr = (valid > 0).sum() / len(valid) * 100 if len(valid) else 0
            liga_stats.append({"Liga": league, "Strategie": label, "Gewinnrate (%)": wr})
 
    liga_df = pd.DataFrame(liga_stats)
    pivot = liga_df.pivot(index="Liga", columns="Strategie", values="Gewinnrate (%)")
 
    fig5, ax5 = plt.subplots(figsize=(10, 3.5))
    fig5.patch.set_facecolor("#0E1117")
    ax5.set_facecolor("#0E1117")
 
    x = np.arange(len(pivot.index))
    width = 0.2
    for i, (strat, color) in enumerate(COLORS.items()):
        if strat in pivot.columns:
            ax5.bar(x + i * width, pivot[strat], width, label=strat, color=color)
 
    ax5.set_xticks(x + width * 1.5)
    ax5.set_xticklabels(pivot.index, color="white")
    ax5.set_ylabel("Gewinnrate (%)", color="white")
    ax5.tick_params(colors="white")
    ax5.spines[:].set_color("#333")
    ax5.legend(facecolor="#1A1D23", labelcolor="white", framealpha=0.8)
    ax5.grid(axis="y", color="#333", linewidth=0.5)
    ax5.axhline(33, color="white", linewidth=0.5, linestyle=":", alpha=0.3)
 
    st.pyplot(fig5)
    plt.close(fig5)
 
# ── Rohdaten ───────────────────────────────────────────────────────────────────
 
st.subheader("Rohdaten")
 
display_cols = [
    "spiel_nr", "csv_date", "home_team", "away_team", "result",
    "poly_home_odds_5min", "poly_draw_odds_5min", "poly_away_odds_5min",
    "profit_home", "profit_draw", "profit_away", "profit_favorite",
    "mapping_quality", "mapping_quality_score",
    "polymarket_match_type", "binary_confidence",
]
show_cols = [c for c in display_cols if c in df.columns]
 
st.dataframe(
    df[show_cols].style.format({
        "poly_home_odds_5min": "{:.3f}",
        "poly_draw_odds_5min": "{:.3f}",
        "poly_away_odds_5min": "{:.3f}",
        "profit_home":     "{:+.2f}",
        "profit_draw":     "{:+.2f}",
        "profit_away":     "{:+.2f}",
        "profit_favorite": "{:+.2f}",
    }),
    use_container_width=True,
)