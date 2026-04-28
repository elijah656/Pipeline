import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt

INPUT_FILE = "polymarket_football_all_sources.csv"

st.set_page_config(
    page_title="Polymarket Strategieanalyse",
    layout="wide"
)

st.title("Polymarket Strategieanalyse")
st.write("Vergleich: Immer 1€ auf Home, Draw oder Away setzen")


def calculate_profit(row, bet_type):
    odds_col = {
        "home": "poly_home_odds_5min",
        "draw": "poly_draw_odds_5min",
        "away": "poly_away_odds_5min",
    }[bet_type]

    result_value = {
        "home": "H",
        "draw": "D",
        "away": "A",
    }[bet_type]

    if pd.isna(row[odds_col]):
        return None

    if row["result"] == result_value:
        return row[odds_col] - 1

    return -1

def calculate_favorite_profit(row):
    odds = {
        "home": row["poly_home_odds_5min"],
        "draw": row["poly_draw_odds_5min"],
        "away": row["poly_away_odds_5min"],
    }

    odds = {k: v for k, v in odds.items() if pd.notna(v)}

    if not odds:
        return None

    favorite = min(odds, key=odds.get)

    result_map = {
        "home": "H",
        "draw": "D",
        "away": "A",
    }

    if row["result"] == result_map[favorite]:
        return odds[favorite] - 1

    return -1


@st.cache_data
def load_data():
    df = pd.read_csv(INPUT_FILE)

    required_cols = [
        "result",
        "poly_home_odds_5min",
        "poly_draw_odds_5min",
        "poly_away_odds_5min",
    ]

    missing = [col for col in required_cols if col not in df.columns]
    if missing:
        st.error(f"Diese Spalten fehlen in der CSV: {missing}")
        st.stop()

    df = df.reset_index(drop=True)
    df["spiel_nr"] = df.index + 1

    df["profit_home"] = df.apply(lambda row: calculate_profit(row, "home"), axis=1)
    df["profit_draw"] = df.apply(lambda row: calculate_profit(row, "draw"), axis=1)
    df["profit_away"] = df.apply(lambda row: calculate_profit(row, "away"), axis=1)
    df["profit_favorite"] = df.apply(calculate_favorite_profit, axis=1)

    df["avg_profit_home"] = df["profit_home"].expanding().mean()
    df["avg_profit_draw"] = df["profit_draw"].expanding().mean()
    df["avg_profit_away"] = df["profit_away"].expanding().mean()
    df["avg_profit_favorite"] = df["profit_favorite"].expanding().mean()

    df["cum_profit_home"] = df["profit_home"].cumsum()
    df["cum_profit_draw"] = df["profit_draw"].cumsum()
    df["cum_profit_away"] = df["profit_away"].cumsum()
    df["cum_profit_favorite"] = df["profit_favorite"].cumsum()

    return df


df = load_data()

st.subheader("Durchschnittlicher Gewinn pro Spiel")

fig1, ax1 = plt.subplots(figsize=(12, 5))

ax1.plot(df["spiel_nr"], df["avg_profit_home"], marker="o", label="Home")
ax1.plot(df["spiel_nr"], df["avg_profit_draw"], marker="o", label="Draw")
ax1.plot(df["spiel_nr"], df["avg_profit_away"], marker="o", label="Away")
ax1.plot(df["spiel_nr"], df["avg_profit_favorite"], marker="o", label="Favorit")

ax1.axhline(0, linestyle="--")
ax1.set_xlabel("Spielnummer")
ax1.set_ylabel("Ø Gewinn pro Spiel (€)")
ax1.set_title("Durchschnittlicher Gewinn pro Spiel bei 1€ Einsatz")
ax1.set_xticks(df["spiel_nr"])
ax1.legend()
ax1.grid(True)

st.pyplot(fig1)

st.subheader("Endgewinn nach allen ausgewerteten Spielen")

final_profits = pd.DataFrame({
    "Strategie": ["Immer Home", "Immer Draw", "Immer Away", "Immer Favorit"],
    "Endgewinn": [
        df["profit_home"].sum(),
        df["profit_draw"].sum(),
        df["profit_away"].sum(),
        df["profit_favorite"].sum(),
    ]
})

fig2, ax2 = plt.subplots(figsize=(8, 5))

ax2.bar(final_profits["Strategie"], final_profits["Endgewinn"])
ax2.axhline(0, linestyle="--")
ax2.set_ylabel("Gewinn (€)")
ax2.set_title("Finaler Gewinn nach allen Spielen")

for i, value in enumerate(final_profits["Endgewinn"]):
    ax2.text(i, value, f"{value:.2f} €", ha="center", va="bottom" if value >= 0 else "top")

st.pyplot(fig2)

st.subheader("Kennzahlen")

col1, col2, col3, col4 = st.columns(4)

col1.metric(
    "Home Strategie",
    f"{df['profit_home'].sum():.2f} €",
    f"Ø {df['profit_home'].mean():.4f} €"
)

col2.metric(
    "Draw Strategie",
    f"{df['profit_draw'].sum():.2f} €",
    f"Ø {df['profit_draw'].mean():.4f} €"
)

col3.metric(
    "Away Strategie",
    f"{df['profit_away'].sum():.2f} €",
    f"Ø {df['profit_away'].mean():.4f} €"
)

col4.metric(
    "Favoriten Strategie",
    f"{df['profit_favorite'].sum():.2f} €",
    f"Ø {df['profit_favorite'].mean():.4f} €"
)

st.subheader("Datenansicht")
st.dataframe(df)