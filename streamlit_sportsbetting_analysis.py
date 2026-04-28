import pandas as pd
import plotly.express as px
import streamlit as st

st.set_page_config(page_title="Sportwetten Analyse", layout="wide")

st.title("⚽ Sportwetten Analyse: Favoritenstrategie mit Closing Odds")
st.write("Strategie: Bei jedem Spiel wird 1€ auf den Favoriten anhand der Closing Odds gesetzt.")

# -----------------------------
# 1. Daten laden
# -----------------------------
url = "https://www.football-data.co.uk/mmz4281/2324/E0.csv"
df = pd.read_csv(url)

# -----------------------------
# 2. Daten bereinigen
# -----------------------------
df["Date"] = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce")
df = df.dropna(subset=["Date", "HomeTeam", "AwayTeam", "FTR"])

# -----------------------------
# 3. Closing-Odds-Anbieter erkennen
# -----------------------------
providers = []

for col in df.columns:
    if col.endswith("CH"):
        prefix = col[:-2]
        if prefix + "CD" in df.columns and prefix + "CA" in df.columns:
            providers.append(prefix)

# Nur echte/relevante Anbieter auswählen
valid_providers = ["B365", "BW", "PS", "WH", "1XB", "BF", "BFE", "Max", "Avg"]
providers = [p for p in providers if p in valid_providers]

st.write("Gefundene Closing-Odds-Anbieter:", providers)

# -----------------------------
# 4. Backtest-Funktion für Closing Odds
# -----------------------------
def calculate_provider_backtest(df, provider):
    temp = df.copy()

    h_col = provider + "CH"
    d_col = provider + "CD"
    a_col = provider + "CA"

    temp = temp.dropna(subset=[h_col, d_col, a_col])

    def get_favorite(row):
        odds = {
            "H": row[h_col],
            "D": row[d_col],
            "A": row[a_col]
        }
        return min(odds, key=odds.get)

    def get_favorite_odds(row):
        if row["favorite"] == "H":
            return row[h_col]
        elif row["favorite"] == "D":
            return row[d_col]
        else:
            return row[a_col]

    temp["provider"] = provider
    temp["favorite"] = temp.apply(get_favorite, axis=1)
    temp["favorite_odds"] = temp.apply(get_favorite_odds, axis=1)

    temp["profit"] = temp.apply(
        lambda row: row["favorite_odds"] - 1 if row["favorite"] == row["FTR"] else -1,
        axis=1
    )

    temp = temp.sort_values("Date")
    temp["cum_profit"] = temp["profit"].cumsum()

    return temp

# -----------------------------
# 5. Backtest für alle Anbieter
# -----------------------------
all_results = []

for provider in providers:
    provider_df = calculate_provider_backtest(df, provider)
    all_results.append(provider_df)

results_df = pd.concat(all_results, ignore_index=True)

# -----------------------------
# 6. Sidebar Filter
# -----------------------------
selected_providers = st.sidebar.multiselect(
    "Anbieter auswählen",
    options=sorted(results_df["provider"].unique()),
    default=sorted(results_df["provider"].unique())
)

filtered_df = results_df[results_df["provider"].isin(selected_providers)].copy()

# -----------------------------
# 7. Kennzahlen
# -----------------------------
summary = filtered_df.groupby("provider", as_index=False).agg(
    total_profit=("profit", "sum"),
    bets=("profit", "count"),
    hit_rate=("profit", lambda x: (x > 0).mean() * 100),
    avg_favorite_odds=("favorite_odds", "mean")
)

summary["roi"] = summary["total_profit"] / summary["bets"] * 100

col1, col2, col3, col4 = st.columns(4)

col1.metric("Anzahl Anbieter", len(selected_providers))
col2.metric("Ø ROI", f"{summary['roi'].mean():.2f}%")
col3.metric("Ø Gewinn", f"{summary['total_profit'].mean():.2f} €")
col4.metric("Ø Favoritenquote", f"{summary['avg_favorite_odds'].mean():.2f}")

# -----------------------------
# 8. Graph 1: Gesamtgewinn je Anbieter
# -----------------------------
fig1 = px.bar(
    summary.sort_values("total_profit", ascending=False),
    x="provider",
    y="total_profit",
    title="Gesamtgewinn: 1€ auf Favorit je Anbieter – Closing Odds",
    labels={
        "provider": "Anbieter",
        "total_profit": "Gesamtgewinn in €"
    },
    hover_data=["bets", "roi", "hit_rate", "avg_favorite_odds"]
)

st.plotly_chart(fig1, use_container_width=True)

# -----------------------------
# 9. Graph 2: ROI je Anbieter
# -----------------------------
fig2 = px.bar(
    summary.sort_values("roi", ascending=False),
    x="provider",
    y="roi",
    title="ROI je Anbieter – Closing Odds",
    labels={
        "provider": "Anbieter",
        "roi": "ROI in %"
    },
    hover_data=["bets", "total_profit", "hit_rate", "avg_favorite_odds"]
)

st.plotly_chart(fig2, use_container_width=True)

# -----------------------------
# 10. Graph 3: Gewinnverlauf je Anbieter
# -----------------------------
fig3 = px.line(
    filtered_df,
    x="Date",
    y="cum_profit",
    color="provider",
    title="Kumulierter Gewinn: 1€ auf Favorit je Anbieter – Closing Odds",
    labels={
        "Date": "Datum",
        "cum_profit": "Kumulierter Gewinn in €",
        "provider": "Anbieter"
    },
    hover_data=["HomeTeam", "AwayTeam", "favorite", "favorite_odds", "FTR", "profit"]
)

st.plotly_chart(fig3, use_container_width=True)

# -----------------------------
# 11. Graph 4: Gewinn nach Quotenbereich
# -----------------------------
filtered_df["odds_bucket"] = pd.cut(
    filtered_df["favorite_odds"],
    bins=[1, 1.3, 1.6, 2.0, 3.0, 5.0, 10.0]
)

bucket_summary = filtered_df.groupby(
    ["provider", "odds_bucket"],
    as_index=False,
    observed=True
)["profit"].sum()

bucket_summary["odds_bucket"] = bucket_summary["odds_bucket"].astype(str)

fig4 = px.bar(
    bucket_summary,
    x="odds_bucket",
    y="profit",
    color="provider",
    barmode="group",
    title="Gewinn nach Quotenbereich je Anbieter – Closing Odds",
    labels={
        "odds_bucket": "Quotenbereich",
        "profit": "Gewinn in €",
        "provider": "Anbieter"
    }
)

st.plotly_chart(fig4, use_container_width=True)

# -----------------------------
# 12. Tabelle
# -----------------------------
st.subheader("Zusammenfassung je Anbieter")

st.dataframe(
    summary.sort_values("total_profit", ascending=False),
    use_container_width=True
)

# -----------------------------
# Gewinnvergleich:
# Favorit-Sieg vs Unentschieden vs Underdog-Sieg
# pro Anbieter mit Closing Odds
# -----------------------------

selected_providers = ["B365", "BW", "BFE", "PS", "WH", "1XB"]

strategy_results = []

for provider in selected_providers:
    h_col = provider + "CH"
    d_col = provider + "CD"
    a_col = provider + "CA"

    if h_col not in df.columns or d_col not in df.columns or a_col not in df.columns:
        continue

    temp = df.dropna(subset=[h_col, d_col, a_col]).copy()

    for _, row in temp.iterrows():

        # Favorit und Underdog nur zwischen Home und Away bestimmen
        if row[h_col] < row[a_col]:
            favorite_result = "H"
            favorite_odds = row[h_col]

            underdog_result = "A"
            underdog_odds = row[a_col]
        else:
            favorite_result = "A"
            favorite_odds = row[a_col]

            underdog_result = "H"
            underdog_odds = row[h_col]

        # Strategie 1: 1€ auf Sieg Favorit
        profit_favorite = favorite_odds - 1 if row["FTR"] == favorite_result else -1

        strategy_results.append({
            "provider": provider,
            "strategy": "Sieg Favorit",
            "profit": profit_favorite
        })

        # Strategie 2: 1€ auf Unentschieden
        profit_draw = row[d_col] - 1 if row["FTR"] == "D" else -1

        strategy_results.append({
            "provider": provider,
            "strategy": "Unentschieden",
            "profit": profit_draw
        })

        # Strategie 3: 1€ auf Sieg Underdog
        profit_underdog = underdog_odds - 1 if row["FTR"] == underdog_result else -1

        strategy_results.append({
            "provider": provider,
            "strategy": "Sieg Underdog",
            "profit": profit_underdog
        })

# DataFrame bauen
strategy_df = pd.DataFrame(strategy_results)

# Gesamtgewinn pro Anbieter und Strategie
strategy_summary = strategy_df.groupby(
    ["provider", "strategy"],
    as_index=False
)["profit"].sum()

# Reihenfolge festlegen
strategy_order = ["Sieg Favorit", "Unentschieden", "Sieg Underdog"]

strategy_summary["strategy"] = pd.Categorical(
    strategy_summary["strategy"],
    categories=strategy_order,
    ordered=True
)

strategy_summary = strategy_summary.sort_values(["provider", "strategy"])

# Gruppiertes Balkendiagramm
fig_strategy = px.bar(
    strategy_summary,
    x="provider",
    y="profit",
    color="strategy",
    barmode="group",
    title="Gewinnvergleich je Anbieter: Favorit, Unentschieden, Underdog",
    labels={
        "provider": "Anbieter",
        "profit": "Gesamtgewinn in €",
        "strategy": "Strategie"
    },
    category_orders={
        "provider": selected_providers,
        "strategy": strategy_order
    }
)

st.plotly_chart(fig_strategy, use_container_width=True)