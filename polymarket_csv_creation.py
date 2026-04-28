import json
import time
import requests
import pandas as pd
from rapidfuzz import fuzz
from zoneinfo import ZoneInfo

FOOTBALL_DATA_SOURCES = [
    {
        "country": "England",
        "league": "Premier League",
        "season": "2025_26",
        "url": "https://www.football-data.co.uk/mmz4281/2526/E0.csv",
    },

    # Weitere Dateien auswerten (z. B. Bundesliga 25/26):
    # {
    #     "country": "Germany",
    #     "league": "Bundesliga",
    #     "season": "2025_26",
    #     "url": "https://www.football-data.co.uk/mmz4281/2526/D1.csv",
    # },
]

POLYMARKET_EVENTS_URL = "https://gamma-api.polymarket.com/events"
POLYMARKET_PRICE_HISTORY_URL = "https://clob.polymarket.com/prices-history"

NUMBER_OF_GAMES = 200
DATE_WINDOW_HOURS = 8
PRICE_MINUTES_BEFORE_KICKOFF = 5
MATCH_THRESHOLD = 45

OUTPUT_FILE = "polymarket_football_all_sources.csv"

TEAM_ALIASES = {
    "Man United": ["Manchester United", "Man Utd", "Man United"],
    "Man City": ["Manchester City", "Man City"],
    "Nott'm Forest": ["Nottingham Forest", "Nottm Forest", "Forest"],
    "Newcastle": ["Newcastle United", "Newcastle"],
    "Tottenham": ["Tottenham Hotspur", "Spurs", "Tottenham"],
    "Wolves": ["Wolverhampton Wanderers", "Wolves"],
    "Brighton": ["Brighton and Hove Albion", "Brighton"],
    "West Ham": ["West Ham United", "West Ham"],
}

# Diese Funktion versucht, ein Feld zu parsen, das entweder als JSON-String oder als bereits geparste Liste vorliegen könnte. Sie gibt die geparste Liste zurück oder
# None, wenn das Parsen fehlschlägt.
def parse_json_field(value):
    if value is None:
        return None
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None
    return None


# Diese Funktion versucht, einen Wert sicher in einen Float umzuwandeln. Wenn der Wert None, ein ungültiger String oder ein anderer Typ ist, wird 0.0 zurückgegeben. 
# Dies verhindert Fehler bei der Verarbeitung von Volumen- oder Preis
def safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


# Diese Funktion normalisiert Text, indem sie ihn in Kleinbuchstaben umwandelt, bestimmte Sonderzeichen entfernt und überflüssige Leerzeichen trimmt. 
# Dies erleichtert die spätere Suche nach Teamnamen im Text von Polymarket-Events und -Märkten.
def normalize_text(text):
    return str(text).lower().replace("'", "").replace(".", "").strip()


# Diese Funktion gibt eine Liste von Varianten eines Teamnamens zurück, die für die Suche verwendet werden können. Sie berücksichtigt sowohl den Originalnamen 
# als auch mögliche Aliase, die in der TEAM_ALIASES-Dictionary definiert sind.
def get_team_variants(team):
    return [team] + TEAM_ALIASES.get(team, [])


# Diese Funktion überprüft, ob der Name eines Teams im gegebenen Text vorkommt. Sie berücksichtigt dabei verschiedene Varianten des Teamnamens und verwendet 
# sowohl direkte Textsuche als auch eine Fuzzy-Matching-Ähnlichkeitsschwelle, um mögliche Erwähnungen zu erkennen.
def team_name_is_in_text(team, text):
    text = normalize_text(text)

    for variant in get_team_variants(team):
        variant_norm = normalize_text(variant)

        if variant_norm in text:
            return True

        if fuzz.partial_ratio(variant_norm, text) >= 90:
            return True

    return False


# Diese Funktion überprüft, ob im Text eines Polymarket-Events oder eines Marktes die Namen des Heim- oder Auswärtsteams vorkommen. Sie gibt zurück, 
# ob mindestens eines der Teams gefunden wurde, sowie separate Flags für Home- und Away-Team-Erwähnungen.
def event_contains_home_or_away_team(row, event, market=None):
    parts = []

    for key in ["title", "slug", "description"]:
        if event.get(key):
            parts.append(str(event.get(key)))

    if market:
        for key in ["question", "title", "slug", "description"]:
            if market.get(key):
                parts.append(str(market.get(key)))

    text = " ".join(parts)

    home_found = team_name_is_in_text(row["HomeTeam"], text)
    away_found = team_name_is_in_text(row["AwayTeam"], text)

    return home_found or away_found, home_found, away_found


# Diese Funktion erstellt aus den "Date" und "Time"-Feldern der CSV einen UTC-Datetime-Objekt, das den Anstoßzeitpunkt des Spiels repräsentiert.
def make_match_datetime_utc(row):
    date_str = row["Date"].strftime("%Y-%m-%d")
    time_str = str(row["Time"]) if "Time" in row and pd.notna(row["Time"]) else "15:00"

    local_dt = pd.to_datetime(f"{date_str} {time_str}", errors="coerce")

    if pd.isna(local_dt):
        return None

    local_dt = local_dt.to_pydatetime().replace(tzinfo=ZoneInfo("Europe/London"))
    return local_dt.astimezone(ZoneInfo("UTC"))


# Diese Funktion extrahiert den relevanten Text aus einem Polymarket-Event, indem sie die wichtigsten Felder des Events und seiner Märkte kombiniert.
def get_event_text(event):
    parts = []

    for key in ["title", "slug", "description"]:
        if event.get(key):
            parts.append(str(event.get(key)))

    markets = event.get("markets", [])

    if isinstance(markets, list):
        for market in markets:
            if not isinstance(market, dict):
                continue
            for key in ["question", "title", "slug", "description"]:
                if market.get(key):
                    parts.append(str(market.get(key)))

    return " ".join(parts).lower()


# Diese Funktion versucht zu bestimmen, ob ein Markt ein potenzielles "Game Outcome"-Markt ist, indem sie nach bestimmten Schlüsselwörtern im Text sucht.
def is_game_outcome_market(market):
    text = " ".join([
        str(market.get("question", "")),
        str(market.get("title", "")),
        str(market.get("slug", "")),
        str(market.get("description", "")),
    ]).lower()

    bad_keywords = [
        "goal", "goals", "player", "shots", "corner", "corners",
        "yellow", "red card", "cards", "assist", "record",
        "over", "under", "spread", "handicap", "total",
        "lineups", "starting", "score exactly"
    ]

    if any(word in text for word in bad_keywords):
        return False

    good_keywords = ["win", "winner", "moneyline", "match winner", "draw", "tie"]

    return any(word in text for word in good_keywords)


# Diese Funktion versucht, das Handelsvolumen eines Marktes zu extrahieren, indem sie verschiedene mögliche Felder überprüft, die dieses Volumen enthalten könnten.
def get_market_volume(market):
    possible_keys = ["volumeNum", "volume", "volumeClob", "liquidity", "liquidityNum"]
    values = [safe_float(market.get(key)) for key in possible_keys]
    return max(values)


# Diese Funktion extrahiert die Outcomes und die zugehörigen Token-IDs aus einem Markt. Sie berücksichtigt, dass diese Informationen entweder als 
# JSON-Strings oder als bereits geparste Listen vorliegen können.
def get_market_outcomes_and_tokens(market):
    outcomes = parse_json_field(market.get("outcomes"))
    token_ids = parse_json_field(market.get("clobTokenIds"))

    if not outcomes or not token_ids:
        return []

    return list(zip(outcomes, token_ids))


# Diese Funktion sucht in den Outcomes eines Marktes nach einem Outcome, dessen Label "Yes" entspricht (case-insensitive). 
# Wenn ein solcher Outcome gefunden wird, wird die zugehörige Token-ID zurückgegeben.
def get_yes_token_id(market):
    outcomes_tokens = get_market_outcomes_and_tokens(market)

    if not outcomes_tokens:
        return None

    for outcome, token_id in outcomes_tokens:
        if str(outcome).lower() == "yes":
            return token_id

    return outcomes_tokens[0][1]


# Diese Funktion versucht, verschiedene Arten von "resolved"-Indikatoren zu interpretieren, um zu bestimmen, ob ein Markt als aufgelöst gilt. 
# Sie berücksichtigt sowohl explizite boolesche Werte als auch typische Schlüsselwörter in Strings.
def parse_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ["true", "yes", "1", "resolved", "winner"]
    return False


# Diese Funktion gibt die gewonnenen Outcomes eines Marktes zurück, die als "resolved" gelten. Sie sucht sowohl nach expliziten Feldern wie "winner" oder "result" 
# als auch nach Outcomes, deren Preis nahe 1.0 liegt, was auf eine Auflösung hindeuten könnte.
def get_resolved_winning_outcomes(market):
    outcomes = parse_json_field(market.get("outcomes"))
    outcome_prices = parse_json_field(market.get("outcomePrices"))

    winners = []

    for key in ["winner", "winningOutcome", "resolvedOutcome", "result", "outcome"]:
        value = market.get(key)
        if value:
            winners.append(str(value))

    if outcomes and outcome_prices and len(outcomes) == len(outcome_prices):
        for outcome, price in zip(outcomes, outcome_prices):
            if safe_float(price) >= 0.99:
                winners.append(str(outcome))

    return winners


# Diese Funktion versucht, das Ergebnis eines 1X2-Marktes zu inferieren, indem sie die gewonnenen Outcomes analysiert und mit den Teamnamen abgleicht. 
# Sie gibt "H", "D" oder "A" zurück, wenn sie das Ergebnis erfolgreich klassifizieren kann, oder None, wenn dies nicht möglich ist.
def infer_poly_result_from_full_1x2(market, row):
    winners = get_resolved_winning_outcomes(market)

    for winner in winners:
        result = classify_outcome_label(winner, row)
        if result:
            return result

    return None


# Diese Funktion versucht, das Ergebnis eines binären Marktes zu inferieren, indem sie zuerst nach expliziten "Yes"/"No"-Ergebnissen sucht und 
# dann die Preise der Outcomes analysiert.
def infer_binary_yes_no(market):
    winners = [normalize_text(x) for x in get_resolved_winning_outcomes(market)]

    if any(x == "yes" for x in winners):
        return True

    if any(x == "no" for x in winners):
        return False

    outcome_prices = parse_json_field(market.get("outcomePrices"))
    outcomes = parse_json_field(market.get("outcomes"))

    if outcomes and outcome_prices and len(outcomes) == len(outcome_prices):
        for outcome, price in zip(outcomes, outcome_prices):
            if normalize_text(outcome) == "yes" and safe_float(price) >= 0.99:
                return True
            if normalize_text(outcome) == "no" and safe_float(price) >= 0.99:
                return False

    return None


# Diese Funktion versucht, basierend auf dem besten gefundenen Markt und dessen Typ, das Ergebnis des Spiels zu inferieren. Sie behandelt verschiedene Marktstrukturen 
# (1X2, binär, kombiniert) und gibt das inferierte Ergebnis sowie die Methode der Inferenz zurück.
def infer_poly_result_from_best(best, row):
    if best["market_type"] == "full_1x2":
        return infer_poly_result_from_full_1x2(best["market"], row), "resolved_full_1x2"

    if best["market_type"] == "binary":
        yes_no = infer_binary_yes_no(best["market"])

        if yes_no is True:
            return best["binary_type"], "resolved_single_binary_yes"

        return None, "single_binary_not_enough_information"

    if best["market_type"] == "binary_combined":
        positive_results = []
        negative_results = []

        for outcome_type, candidate in best["binary_markets"].items():
            yes_no = infer_binary_yes_no(candidate["market"])

            if yes_no is True:
                positive_results.append(outcome_type)
            elif yes_no is False:
                negative_results.append(outcome_type)

        if len(positive_results) == 1:
            return positive_results[0], "resolved_binary_combined_yes"

        if "H" in negative_results and "A" in negative_results:
            return "D", "inferred_draw_from_home_and_away_no"

        return None, "binary_combined_not_enough_information"

    return None, "unknown_market_type"


# Diese Funktion vergleicht das aus Polymarket inferierte Ergebnis mit dem in der CSV angegebenen Ergebnis. Sie gibt das inferierte Ergebnis, die Methode der Inferenz und
# ob es eine Übereinstimmung mit der CSV gibt, zurück. Wenn das CSV-Ergebnis fehlt oder die Inferenz nicht möglich ist, werden entsprechende Informationen zurückgegeben.
def compare_poly_result_with_csv(best, row):
    csv_result = row.get("FTR")

    if pd.isna(csv_result):
        return None, "csv_result_missing", False

    poly_result, method = infer_poly_result_from_best(best, row)

    if poly_result is None:
        return None, method, False

    return poly_result, method, poly_result == csv_result


# Diese Funktion versucht, die Art eines Marktergebnisses zu klassifizieren (Heimsieg, Unentschieden, Auswärtssieg) basierend auf dem Text des Ergebnisses 
# und der Teamnamen.
def classify_outcome_label(label, row):
    label_norm = normalize_text(label)

    home_variants = [normalize_text(x) for x in get_team_variants(row["HomeTeam"])]
    away_variants = [normalize_text(x) for x in get_team_variants(row["AwayTeam"])]

    if any(v in label_norm for v in home_variants):
        return "H"

    if any(v in label_norm for v in away_variants):
        return "A"

    if "draw" in label_norm or "tie" in label_norm:
        return "D"

    return None

# Diese Funktion versucht, binäre Märkte zu klassifizieren, indem sie prüft, ob die Teamnamen im Markttext vorkommen oder ob typische Schlüsselwörter 
# für Unentschieden vorhanden sind.
def classify_binary_market(market, row):
    text = normalize_text(" ".join([
        str(market.get("question", "")),
        str(market.get("title", "")),
        str(market.get("slug", "")),
        str(market.get("description", "")),
    ]))

    if "draw" in text or "tie" in text:
        return "D"

    if team_name_is_in_text(row["HomeTeam"], text):
        return "H"

    if team_name_is_in_text(row["AwayTeam"], text):
        return "A"

    return None

# Diese Funktion ruft den Preis eines bestimmten Tokens etwa 5 Minuten vor dem Anstoßzeitpunkt ab, um eine Art "Pseudo-Schlusskurs / Closing Odds" zu erhalten. 
# Sie sucht in der Preis-Historie nach dem Preis, der am nächsten zum Zielzeitpunkt liegt, und gibt diesen Preis sowie den Zeitstempel zurück. 
# Wenn kein Preis gefunden wird, werden None-Werte zurückgegeben.
def get_price_5_min_before_kickoff(token_id, kickoff_utc):
    target_ts = int(kickoff_utc.timestamp()) - PRICE_MINUTES_BEFORE_KICKOFF * 60

    params = {
        "market": token_id,
        "startTs": target_ts - 60 * 60,
        "endTs": target_ts + 60,
        "fidelity": 1,
    }

    response = requests.get(POLYMARKET_PRICE_HISTORY_URL, params=params, timeout=20)
    response.raise_for_status()

    data = response.json()
    history = data.get("history", [])

    if not history:
        return None, None

    before_target = [p for p in history if int(p["t"]) <= target_ts]

    if before_target:
        chosen = max(before_target, key=lambda x: int(x["t"]))
    else:
        chosen = min(history, key=lambda x: abs(int(x["t"]) - target_ts))

    price = float(chosen["p"])
    price_ts = pd.to_datetime(int(chosen["t"]), unit="s", utc=True)

    return price, price_ts

# Diese Funktion lädt die Fußballspieldaten aus der angegebenen CSV-URL, bereinigt sie und fügt zusätzliche Informationen hinzu. Sie gibt einen DataFrame zurück, 
# der für die weitere Verarbeitung bereit ist. Optional kann die Anzahl der Spiele begrenzt werden, die zurückgegeben werden sollen, um die Verarbeitung zu beschleunigen.
def load_football_data(source, number_of_games=None):
    df = pd.read_csv(source["url"])

    df["Date"] = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce")
    df = df.dropna(subset=["Date", "HomeTeam", "AwayTeam"])

    if "Time" not in df.columns:
        df["Time"] = "15:00"

    df = df.sort_values(["Date", "Time"])

    df["country"] = source["country"]
    df["league"] = source["league"]
    df["season"] = source["season"]
    df["source_url"] = source["url"]

    if number_of_games is not None:
        return df.head(number_of_games)

    return df

# Diese Funktion ruft alle Polymarket-Events ab, die innerhalb eines bestimmten Zeitfensters um den Anstoßzeitpunkt eines Fußballspiels liegen.
def fetch_events_for_match(kickoff_utc):
    start = kickoff_utc - pd.Timedelta(hours=DATE_WINDOW_HOURS)
    end = kickoff_utc + pd.Timedelta(hours=DATE_WINDOW_HOURS)

    all_events = []
    limit = 100
    offset = 0

    while offset < 500:
        params = {
            "closed": "true",
            "limit": limit,
            "offset": offset,
            "end_date_min": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end_date_max": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

        response = requests.get(POLYMARKET_EVENTS_URL, params=params, timeout=20)
        response.raise_for_status()

        events = response.json()

        if not events:
            break

        all_events.extend(events)

        if len(events) < limit:
            break

        offset += limit

    return all_events

# Diese Funktion bewertet, wie gut ein Polymarket-Event zu einem Fußballspiel passt, basierend auf der Ähnlichkeit der Teamnamen im Event-Text und der Marktstruktur. 
# Sie gibt einen kombinierten Score zurück, sowie separate Scores für Home- und Away-Team-Erwähnungen.
def score_event_against_match(row, event):
    event_text = get_event_text(event)

    home_variants = get_team_variants(row["HomeTeam"])
    away_variants = get_team_variants(row["AwayTeam"])

    home_score = max(fuzz.partial_ratio(team.lower(), event_text) for team in home_variants)
    away_score = max(fuzz.partial_ratio(team.lower(), event_text) for team in away_variants)

    combined_score = (home_score + away_score) / 2

    return combined_score, home_score, away_score

# Diese Funktion sucht für ein gegebenes Fußballspiel (repräsentiert durch eine Zeile aus der CSV) den besten passenden Markt unter den Polymarket-Events, 
# die im relevanten Zeitfenster liegen. Sie bewertet die Events basierend auf der Ähnlichkeit der Teamnamen und der Marktstruktur (1X2 vs. binär) und gibt 
# das am besten passende Event/Markt zurück.
def find_best_market_for_match(row, events):
    full_1x2_candidates = []
    binary_candidates = []

    for event in events:
        markets = event.get("markets", [])

        if not isinstance(markets, list):
            continue

        for market in markets:
            if not isinstance(market, dict):
                continue

            if not market.get("closed", False):
                continue

            if not is_game_outcome_market(market):
                continue

            contains_team, home_found, away_found = event_contains_home_or_away_team(row, event, market)

            if not contains_team:
                continue

            event_score, home_score, away_score = score_event_against_match(row, event)

            if event_score < MATCH_THRESHOLD:
                continue

            volume = get_market_volume(market)
            outcomes_tokens = get_market_outcomes_and_tokens(market)

            outcome_map = {}

            for outcome_label, token_id in outcomes_tokens:
                outcome_type = classify_outcome_label(outcome_label, row)

                if outcome_type:
                    outcome_map[outcome_type] = {
                        "label": outcome_label,
                        "token_id": token_id
                    }

            if all(x in outcome_map for x in ["H", "D", "A"]):
                full_1x2_candidates.append({
                    "event": event,
                    "market": market,
                    "market_type": "full_1x2",
                    "outcome_map": outcome_map,
                    "event_score": event_score,
                    "home_score": home_score,
                    "away_score": away_score,
                    "home_found": home_found,
                    "away_found": away_found,
                    "volume": volume,
                })
            else:
                binary_type = classify_binary_market(market, row)
                yes_token = get_yes_token_id(market)

                if binary_type and yes_token:
                    binary_candidates.append({
                        "event": event,
                        "market": market,
                        "market_type": "binary",
                        "binary_type": binary_type,
                        "yes_token_id": yes_token,
                        "event_score": event_score,
                        "home_score": home_score,
                        "away_score": away_score,
                        "home_found": home_found,
                        "away_found": away_found,
                        "volume": volume,
                    })

    if full_1x2_candidates:
        return max(full_1x2_candidates, key=lambda x: x["volume"])

    if binary_candidates:
        best_by_type = {}

        for candidate in binary_candidates:
            outcome_type = candidate["binary_type"]

            if outcome_type not in best_by_type:
                best_by_type[outcome_type] = candidate
            elif candidate["volume"] > best_by_type[outcome_type]["volume"]:
                best_by_type[outcome_type] = candidate

        if len(best_by_type) >= 2:
            return {
                "market_type": "binary_combined",
                "event": list(best_by_type.values())[0]["event"],
                "market": None,
                "binary_markets": best_by_type,
                "volume": sum(x["volume"] for x in best_by_type.values()),
                "event_score": max(x["event_score"] for x in best_by_type.values()),
                "home_score": max(x["home_score"] for x in best_by_type.values()),
                "away_score": max(x["away_score"] for x in best_by_type.values()),
                "home_found": any(x["home_found"] for x in best_by_type.values()),
                "away_found": any(x["away_found"] for x in best_by_type.values()),
            }

        return max(binary_candidates, key=lambda x: x["volume"])

    return None

# Wenn kein passender Markt gefunden wird, erstellen wir trotzdem einen Eintrag mit den verfügbaren Informationen aus der CSV und None für die Polymarket-bezogenen Felder.
def empty_result(row, kickoff_utc):
    return {
        
        "country": row.get("country"),
        "league": row.get("league"),
        "season": row.get("season"),
        "source_url": row.get("source_url"),
        
        "csv_date": row["Date"],
        "csv_time": row["Time"],
        "home_team": row["HomeTeam"],
        "away_team": row["AwayTeam"],
        "kickoff_utc": kickoff_utc,
        
        "home_goals": row.get("FTHG"),
        "away_goals": row.get("FTAG"),
        "result": row.get("FTR"),
        
        "polymarket_event_id": None,
        "polymarket_event_title": None,
        "polymarket_event_slug": None,
        "polymarket_url": None,
        "polymarket_match_type": None,
        "polymarket_market_ids": None,
        "polymarket_market_questions": None,
        "polymarket_market_slugs": None,
        "market_volume": None,
        
        "poly_home_price_5min": None,
        "poly_draw_price_5min": None,
        "poly_away_price_5min": None,
        
        "poly_home_odds_5min": None,
        "poly_draw_odds_5min": None,
        "poly_away_odds_5min": None,
        
        "price_ts_home": None,
        "price_ts_draw": None,
        "price_ts_away": None,
        "event_score": None,
        "home_score": None,
        "away_score": None,
        "home_found_in_poly_text": False,
        "away_found_in_poly_text": False,
        
        "poly_resolved_result": None,
        "poly_result_check_method": None,
        "poly_result_matches_csv": False,
        "mapping_quality": "no_market_found",
    }
    
# Eingabefunktion damit der Nutzer die Anzahl der zu vergleichenden Spiele eingeben kann. Wenn der Nutzer ENTER drückt, werden alle Spiele verarbeitet.
def ask_number_of_games():
    user_input = input(
        "Wie viele Spiele sollen pro CSV verglichen werden? "
        "Zahl eingeben oder ENTER für alle Spiele: "
    ).strip()

    if user_input == "":
        return None

    try:
        number = int(user_input)
        if number <= 0:
            print("Ungültige Zahl. Es werden alle Spiele verarbeitet.")
            return None
        return number
    except ValueError:
        print("Ungültige Eingabe. Es werden alle Spiele verarbeitet.")
        return None


# Hauptfunktion, die den gesamten Prozess steuert: Laden der Daten, Vergleichen mit Polymarket, Extrahieren der Preise und Speichern der Ergebnisse in einer CSV-Datei.
# Sie iteriert über die Fußballspiele, sucht die passenden Polymarket-Events und Märkte, extrahiert die relevanten Informationen und speichert alles in einer
# strukturierten Form.
def main():
    number_of_games = ask_number_of_games()
    results = []

    for source in FOOTBALL_DATA_SOURCES:
        football_df = load_football_data(source, number_of_games)

        print("\n==============================")
        print(f"Liga: {source['league']}")
        print(f"Saison: {source['season']}")
        print(f"Spiele in diesem Lauf: {len(football_df)}")
        print("==============================")

        for _, row in football_df.iterrows():
            kickoff_utc = make_match_datetime_utc(row)

            if kickoff_utc is None:
                continue

            print(f"\nSuche: {row['Date'].date()} {row['Time']} | {row['HomeTeam']} vs {row['AwayTeam']}")

            events = fetch_events_for_match(kickoff_utc)
            print(f"Polymarket Events im Zeitfenster: {len(events)}")

            best = find_best_market_for_match(row, events)

            if not best:
                print("Kein passender Markt gefunden.")
                results.append(empty_result(row, kickoff_utc))
                continue

            event = best["event"]
        
            poly_resolved_result, poly_result_check_method, poly_result_matches_csv = compare_poly_result_with_csv(best, row)

            if poly_result_matches_csv:
                mapping_quality = "verified_result_match"
            elif poly_resolved_result is None:
                mapping_quality = "matched_but_result_not_verifiable"
            else:
                mapping_quality = "danger_mismatch"

            price_home = price_draw = price_away = None
            odds_home = odds_draw = odds_away = None
            price_ts_home = price_ts_draw = price_ts_away = None

            market_questions = []
            market_ids = []
            market_slugs = []

            if best["market_type"] == "full_1x2":
                market = best["market"]
                outcome_map = best["outcome_map"]

                market_questions.append(market.get("question"))
                market_ids.append(market.get("id"))
                market_slugs.append(market.get("slug"))

                for outcome_type, info in outcome_map.items():
                    token_id = info["token_id"]

                    try:
                        price, price_ts = get_price_5_min_before_kickoff(token_id, kickoff_utc)
                    except requests.HTTPError:
                        price, price_ts = None, None

                    odds = 1 / price if price and price > 0 else None

                    if outcome_type == "H":
                        price_home, odds_home, price_ts_home = price, odds, price_ts
                    elif outcome_type == "D":
                        price_draw, odds_draw, price_ts_draw = price, odds, price_ts
                    elif outcome_type == "A":
                        price_away, odds_away, price_ts_away = price, odds, price_ts

            elif best["market_type"] == "binary_combined":
                for outcome_type, candidate in best["binary_markets"].items():
                    market = candidate["market"]
                    token_id = candidate["yes_token_id"]

                    market_questions.append(market.get("question"))
                    market_ids.append(market.get("id"))
                    market_slugs.append(market.get("slug"))

                    try:
                        price, price_ts = get_price_5_min_before_kickoff(token_id, kickoff_utc)
                    except requests.HTTPError:
                        price, price_ts = None, None

                    odds = 1 / price if price and price > 0 else None

                    if outcome_type == "H":
                        price_home, odds_home, price_ts_home = price, odds, price_ts
                    elif outcome_type == "D":
                        price_draw, odds_draw, price_ts_draw = price, odds, price_ts
                    elif outcome_type == "A":
                        price_away, odds_away, price_ts_away = price, odds, price_ts

            else:
                market = best["market"]
                outcome_type = best["binary_type"]
                token_id = best["yes_token_id"]

                market_questions.append(market.get("question"))
                market_ids.append(market.get("id"))
                market_slugs.append(market.get("slug"))

                try:
                    price, price_ts = get_price_5_min_before_kickoff(token_id, kickoff_utc)
                except requests.HTTPError:
                    price, price_ts = None, None

                odds = 1 / price if price and price > 0 else None

                if outcome_type == "H":
                    price_home, odds_home, price_ts_home = price, odds, price_ts
                elif outcome_type == "D":
                    price_draw, odds_draw, price_ts_draw = price, odds, price_ts
                elif outcome_type == "A":
                    price_away, odds_away, price_ts_away = price, odds, price_ts

            print(f"Event: {event.get('title')}")
            print(f"Typ: {best['market_type']}")
            print(f"Markets: {' | '.join([str(x) for x in market_questions])}")
            print(f"Home odds: {odds_home}, Draw odds: {odds_draw}, Away odds: {odds_away}")
            print(f"CSV Ergebnis: {row.get('FTR')}")
            print(f"Polymarket Ergebnis: {poly_resolved_result}")
            print(f"Ergebnis-Check: {mapping_quality}")

            results.append({
                "country": row.get("country"),
                "league": row.get("league"),
                "season": row.get("season"),
                "source_url": row.get("source_url"),
                
                "csv_date": row["Date"],
                "csv_time": row["Time"],
                "home_team": row["HomeTeam"],
                "away_team": row["AwayTeam"],
                "kickoff_utc": kickoff_utc,
            
                "home_goals": row.get("FTHG"),
                "away_goals": row.get("FTAG"),
                "result": row.get("FTR"),

                "polymarket_event_id": event.get("id"),
                "polymarket_event_title": event.get("title"),
                "polymarket_event_slug": event.get("slug"),
                "polymarket_url": f"https://polymarket.com/event/{event.get('slug')}" if event.get("slug") else None,
                "polymarket_match_type": best["market_type"],
                "polymarket_market_ids": " | ".join([str(x) for x in market_ids]),
                "polymarket_market_questions": " | ".join([str(x) for x in market_questions]),
                "polymarket_market_slugs": " | ".join([str(x) for x in market_slugs]),
                "market_volume": best["volume"],
                "poly_home_price_5min": price_home,
                "poly_draw_price_5min": price_draw,
                "poly_away_price_5min": price_away,
                "poly_home_odds_5min": odds_home,
                "poly_draw_odds_5min": odds_draw,
                "poly_away_odds_5min": odds_away,
                "price_ts_home": price_ts_home,
                "price_ts_draw": price_ts_draw,
                "price_ts_away": price_ts_away,
                "event_score": best["event_score"],
                "home_score": best["home_score"],
                "away_score": best["away_score"],
                "home_found_in_poly_text": best["home_found"],
                "away_found_in_poly_text": best["away_found"],

                "polymarket_resolved_result": poly_resolved_result,
                "polymarket_result_check_method": poly_result_check_method,
                "polymarket_result_matches_csv": poly_result_matches_csv,
                "mapping_quality": mapping_quality,
            })

            time.sleep(0.2)

        result_df = pd.DataFrame(results)
        result_df.to_csv(OUTPUT_FILE, index=False)

        print(f"\nGespeichert als: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()