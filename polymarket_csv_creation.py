import json
import time
import requests
import pandas as pd
from rapidfuzz import fuzz
from zoneinfo import ZoneInfo
import re
import unicodedata

FOOTBALL_DATA_SOURCES = [
    {
        "country": "England",
        "league": "Premier League",
        "season": "2025_26",
        "url": "https://www.football-data.co.uk/mmz4281/2526/E0.csv",
    },
    {
        "country": "England",
        "league": "Premier League",
        "season": "2024_25",
        "url": "https://www.football-data.co.uk/mmz4281/2425/E0.csv",
    },
    {
        "country": "Germany",
        "league": "Bundesliga",
        "season": "2025_26",
        "url": "https://www.football-data.co.uk/mmz4281/2526/D1.csv",
    },
    {
        "country": "Germany",
        "league": "Bundesliga",
        "season": "2024_25",
        "url": "https://www.football-data.co.uk/mmz4281/2425/D1.csv",
    },
    {
        "country": "Spain",
        "league": "La Liga",
        "season": "2025_26",
        "url": "https://www.football-data.co.uk/mmz4281/2526/SP1.csv",
    },
    {
        "country": "Spain",
        "league": "La Liga",
        "season": "2024_25",
        "url": "https://www.football-data.co.uk/mmz4281/2425/SP1.csv",
    },
]

POLYMARKET_EVENTS_URL = "https://gamma-api.polymarket.com/events"
POLYMARKET_PRICE_HISTORY_URL = "https://clob.polymarket.com/prices-history"

NUMBER_OF_GAMES = 200
DATE_WINDOW_HOURS = 8
PRICE_MINUTES_BEFORE_KICKOFF = 5
MATCH_THRESHOLD = 45

OUTPUT_FILE = "polymarket_football_all_sources.csv"

# ─────────────────────────────────────────────
# MAPPING QUALITY LEVELS (für CSV-Filterung)
# ─────────────────────────────────────────────
# TIER 1 – beste Qualität, sicher verwenden
QUALITY_VERIFIED_FULL_1X2       = "1_verified_full_1x2"          # 3-Weg-Markt, Ergebnis stimmt mit CSV überein
QUALITY_VERIFIED_BINARY_COMBINED = "1_verified_binary_combined"   # alle 3 Binär-Märkte, Ergebnis stimmt

# TIER 2 – gut, aber kein Ergebnis-Check möglich (Spiel noch nicht aufgelöst)
QUALITY_MATCHED_FULL_1X2        = "2_matched_full_1x2"            # 3-Weg-Markt gefunden, kein Ergebnis in CSV
QUALITY_MATCHED_BINARY_COMBINED = "2_matched_binary_combined"     # alle 3 Binär-Märkte, kein Ergebnis in CSV

# TIER 3 – eingeschränkt (nur 2 Binär-Märkte oder kein Draw-Markt)
QUALITY_PARTIAL_BINARY          = "3_partial_binary"              # nur H+A oder H/A einzeln, Ergebnis bestätigt
QUALITY_PARTIAL_BINARY_UNVERIFIED = "3_partial_binary_unverified" # nur H+A, kein Ergebnis-Check

# TIER 4 – Warnstufe
QUALITY_MISMATCH                = "4_danger_mismatch"             # Ergebnis stimmt NICHT überein → Mapping falsch
QUALITY_SINGLE_BINARY           = "4_single_binary"               # nur 1 Binär-Markt gefunden

# TIER 5 – kein Match
QUALITY_NO_MARKET               = "5_no_market_found"

TEAM_ALIASES = {
    # Premier League
    "Man United":     ["Manchester United", "Man Utd", "Man United"],
    "Man City":       ["Manchester City", "Man City"],
    "Nott'm Forest":  ["Nottingham Forest", "Nottm Forest", "Forest"],
    "Newcastle":      ["Newcastle United", "Newcastle"],
    "Tottenham":      ["Tottenham Hotspur", "Spurs", "Tottenham"],
    "Wolves":         ["Wolverhampton Wanderers", "Wolves"],
    "Brighton":       ["Brighton and Hove Albion", "Brighton"],
    "West Ham":       ["West Ham United", "West Ham"],
    # Bundesliga
    "Bayern Munich":      ["bayern", "bayern munich", "fc bayern", "fcb"],
    "Borussia Dortmund":  ["dortmund", "bvb", "borussia dortmund"],
    "RB Leipzig":         ["leipzig", "rb leipzig", "rbl"],
    "Bayer Leverkusen":   ["leverkusen", "bayer leverkusen"],
    "Eintracht Frankfurt":["frankfurt", "eintracht frankfurt"],
    "VfL Wolfsburg":      ["wolfsburg", "vfl wolfsburg"],
    "M'gladbach":         ["gladbach", "monchengladbach", "moenchengladbach", "bmg", "borussia moenchengladbach"],
    "SC Freiburg":        ["freiburg", "sc freiburg"],
    "FC Augsburg":        ["augsburg", "fc augsburg"],
    "Mainz":              ["mainz", "mainz 05"],
    "TSG Hoffenheim":     ["hoffenheim", "tsg hoffenheim"],
    "Werder Bremen":      ["bremen", "werder", "werder bremen"],
    "VfB Stuttgart":      ["stuttgart", "vfb stuttgart"],
    "Union Berlin":       ["union berlin", "union", "berlin union"],
    "1. FC Koln":         ["koln", "koeln", "fc koln", "fc koeln"],
    "VfL Bochum":         ["bochum", "vfl bochum"],
    "Heidenheim":         ["heidenheim", "fc heidenheim"],
    "St Pauli":           ["st pauli", "pauli", "fc st pauli"],
    # La Liga
    "Real Madrid":        ["real madrid", "madrid", "rm"],
    "Barcelona":          ["barcelona", "barca", "fc barcelona"],
    "Atletico Madrid":    ["atletico", "atletico madrid", "atm"],
    "Sevilla":            ["sevilla", "fc sevilla"],
    "Real Sociedad":      ["sociedad", "real sociedad"],
    "Villarreal":         ["villarreal", "villareal"],
    "Real Betis":         ["betis", "real betis"],
    "Ath Bilbao":         ["athletic bilbao", "bilbao", "ath bilbao"],
    "Valencia":           ["valencia", "fc valencia"],
    "Getafe":             ["getafe"],
    "Celta":              ["celta", "celta vigo"],
    "Osasuna":            ["osasuna"],
    "Mallorca":           ["mallorca"],
    "Granada":            ["granada"],
    "Alaves":             ["alaves", "deportivo alaves"],
    "Cadiz":              ["cadiz"],
    "Las Palmas":         ["las palmas"],
    "Girona":             ["girona"],
    "Rayo Vallecano":     ["rayo", "rayo vallecano"],
    "Espanyol":           ["espanyol", "rcd espanyol"],
}


# ─────────────────────────────────────────────
# HILFSFUNKTIONEN
# ─────────────────────────────────────────────

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


def safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def normalize_text(text):
    text = unicodedata.normalize("NFKD", str(text))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def get_team_variants(team):
    return [team] + TEAM_ALIASES.get(team, [])


def team_name_is_in_text(team, text):
    """Gibt True zurück, wenn eine Teamnamen-Variante im Text vorkommt."""
    text_norm = normalize_text(text)
    for variant in get_team_variants(team):
        variant_norm = normalize_text(variant)
        if variant_norm in text_norm:
            return True
        if fuzz.partial_ratio(variant_norm, text_norm) >= 90:
            return True
    return False


def get_best_team_match_score(team, text_norm):
    """
    Gibt den besten Fuzzy-Match-Score einer Teamnamen-Variante im normalisierten Text zurück.
    Exakte Substring-Matches werden mit Score 100 bewertet.
    """
    best = 0
    for variant in get_team_variants(team):
        variant_norm = normalize_text(variant)
        if variant_norm in text_norm:
            best = max(best, 100)
        else:
            best = max(best, fuzz.partial_ratio(variant_norm, text_norm))
    return best


# ─────────────────────────────────────────────
# NEU: BEIDE TEAMS MÜSSEN IM EVENT-TEXT VORKOMMEN
# ─────────────────────────────────────────────

def both_teams_in_text(row, text):
    """
    Strenge Prüfung: BEIDE Teams (Heim und Auswärts) müssen im Text vorkommen.
    Gibt (both_found, home_score, away_score) zurück.
    """
    text_norm = normalize_text(text)
    home_score = get_best_team_match_score(row["HomeTeam"], text_norm)
    away_score = get_best_team_match_score(row["AwayTeam"], text_norm)
    both_found = home_score >= 80 and away_score >= 80
    return both_found, home_score, away_score


def get_combined_event_market_text(event, market=None):
    parts = []
    for key in ["title", "slug", "description"]:
        if event.get(key):
            parts.append(str(event.get(key)))
    if market:
        for key in ["question", "title", "slug", "description"]:
            if market.get(key):
                parts.append(str(market.get(key)))
    return " ".join(parts)


def event_contains_both_teams(row, event, market=None):
    """
    Gibt zurück, ob BEIDE Teams im kombinierten Event+Markt-Text gefunden werden.
    Dies verhindert, dass ein Markt für ein einzelnes Team einem falschen Spiel zugeordnet wird.
    """
    text = get_combined_event_market_text(event, market)
    both_found, home_score, away_score = both_teams_in_text(row, text)
    return both_found, home_score, away_score


# ─────────────────────────────────────────────
# NEU: DIREKTIONALE BINARY-MARKT-ANALYSE
# "Will Real Madrid beat Barcelona?" → Heimteam-Sieg bei Yes
# ─────────────────────────────────────────────

# Muster: "Will TEAM_A beat/defeat/win against TEAM_B?"
# Das erste Team in solchen Formulierungen ist bei Yes-Auflösung der Sieger.
DIRECTIONAL_PATTERNS = [
    # "Will X beat Y" / "Will X defeat Y" / "Will X win against Y"
    r"will\s+(?P<winner>.+?)\s+(?:beat|defeat|win\s+(?:against|vs\.?|versus))\s+(?P<loser>.+?)(?:\?|$)",
    # "X to beat Y" / "X to defeat Y"
    r"(?P<winner>.+?)\s+to\s+(?:beat|defeat)\s+(?P<loser>.+?)(?:\?|$)",
    # "X beats Y" / "X defeats Y"
    r"(?P<winner>.+?)\s+(?:beats|defeats)\s+(?P<loser>.+?)(?:\?|$)",
    # "X win vs Y"
    r"(?P<winner>.+?)\s+win\s+(?:vs\.?|versus|against)\s+(?P<loser>.+?)(?:\?|$)",
]

def parse_directional_binary(market_text_norm, row):
    """
    Analysiert einen binären Markt-Text auf direktionale Formulierungen.
    Gibt zurück: ("H"|"A"|"D"|None, confidence)
    
    Beispiel: "will real madrid beat barcelona"
      → winner_team = real madrid = HomeTeam → "H" bei Yes
    
    confidence:
      2 = beide Teams eindeutig erkannt (sicherste Zuordnung)
      1 = nur ein Team erkannt, aus Kontext ableitbar
      0 = nicht erkennbar
    """
    home_team = row["HomeTeam"]
    away_team = row["AwayTeam"]

    # Draw-Erkennung
    if re.search(r"\bdraw\b|\btie\b|\bdraw or tie\b", market_text_norm):
        return "D", 2

    for pattern in DIRECTIONAL_PATTERNS:
        match = re.search(pattern, market_text_norm)
        if not match:
            continue

        winner_fragment = match.group("winner").strip()
        loser_fragment  = match.group("loser").strip()

        winner_is_home = get_best_team_match_score(home_team, winner_fragment) >= 75
        winner_is_away = get_best_team_match_score(away_team, winner_fragment) >= 75
        loser_is_home  = get_best_team_match_score(home_team, loser_fragment) >= 75
        loser_is_away  = get_best_team_match_score(away_team, loser_fragment) >= 75

        # Beide Teams eindeutig erkannt → höchste Konfidenz
        if winner_is_home and loser_is_away:
            return "H", 2
        if winner_is_away and loser_is_home:
            return "A", 2

        # Nur Sieger erkannt
        if winner_is_home and not winner_is_away:
            return "H", 1
        if winner_is_away and not winner_is_home:
            return "A", 1

    # Fallback: generische Positionssuche ("X wins", "X moneyline")
    # Suche nach dem Team, das als Sieger erscheint
    for team, result_type in [(home_team, "H"), (away_team, "A")]:
        for variant in get_team_variants(team):
            v = normalize_text(variant)
            if not v:
                continue
            win_patterns = [
                rf"\b{re.escape(v)}\s+(?:to\s+)?win\b",
                rf"\b{re.escape(v)}\s+wins\b",
                rf"\b{re.escape(v)}\s+moneyline\b",
                rf"\bwill\s+{re.escape(v)}\s+win\b",
            ]
            if any(re.search(p, market_text_norm) for p in win_patterns):
                return result_type, 1

    return None, 0


def classify_binary_market_directional(market, row):
    """
    Verbesserte Binary-Klassifizierung:
    1. Direktionale Analyse (z.B. "Will X beat Y?")
    2. Prüft, ob BEIDE Teams im Text vorkommen → stärkere Zuordnung
    3. Fallback auf einfache Team-Nennung
    
    Gibt (outcome_type, confidence) zurück:
      outcome_type: "H", "A", "D" oder None
      confidence: 0–3
    """
    text = " ".join([
        str(market.get("question", "")),
        str(market.get("title", "")),
        str(market.get("slug", "")),
        str(market.get("description", "")),
    ])
    text_norm = normalize_text(text)

    # Draw-Erkennung zuerst
    if re.search(r"\bdraw\b|\btie\b", text_norm):
        return "D", 2

    # Direktionale Analyse
    directional_result, directional_conf = parse_directional_binary(text_norm, row)

    if directional_result and directional_conf >= 1:
        # Prüfe ob auch das zweite Team im Text vorkommt → Konfidenz erhöhen
        home_in_text = team_name_is_in_text(row["HomeTeam"], text_norm)
        away_in_text = team_name_is_in_text(row["AwayTeam"], text_norm)

        if home_in_text and away_in_text:
            # Beide Teams erkannt → maximal sicher
            return directional_result, min(directional_conf + 1, 3)
        else:
            return directional_result, directional_conf

    # Fallback: Team-Nennung ohne direktionale Formulierung
    home_score = get_best_team_match_score(row["HomeTeam"], text_norm)
    away_score = get_best_team_match_score(row["AwayTeam"], text_norm)

    if home_score >= 80 and away_score >= 80:
        # Beide Teams erwähnt aber kein klares Sieger-Muster → unzuverlässig
        return None, 0
    elif home_score >= 80:
        return "H", 1
    elif away_score >= 80:
        return "A", 1

    return None, 0


# ─────────────────────────────────────────────
# MARKT-HILFSFUNKTIONEN (unverändert / leicht angepasst)
# ─────────────────────────────────────────────

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
        "lineups", "starting", "score exactly",
    ]
    if any(word in text for word in bad_keywords):
        return False

    good_keywords = ["win", "winner", "moneyline", "match winner", "draw", "tie", "beat", "defeat"]
    return any(word in text for word in good_keywords)


def get_market_volume(market):
    possible_keys = ["volumeNum", "volume", "volumeClob", "liquidity", "liquidityNum"]
    return max(safe_float(market.get(key)) for key in possible_keys)


def get_market_outcomes_and_tokens(market):
    outcomes   = parse_json_field(market.get("outcomes"))
    token_ids  = parse_json_field(market.get("clobTokenIds"))
    if not outcomes or not token_ids:
        return []
    return list(zip(outcomes, token_ids))


def get_yes_token_id(market):
    outcomes_tokens = get_market_outcomes_and_tokens(market)
    if not outcomes_tokens:
        return None
    for outcome, token_id in outcomes_tokens:
        if str(outcome).lower() == "yes":
            return token_id
    return outcomes_tokens[0][1]


def parse_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ["true", "yes", "1", "resolved", "winner"]
    return False


def get_resolved_winning_outcomes(market):
    outcomes       = parse_json_field(market.get("outcomes"))
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


def classify_outcome_label(label, row):
    label_norm    = normalize_text(label)
    home_variants = [normalize_text(x) for x in get_team_variants(row["HomeTeam"])]
    away_variants = [normalize_text(x) for x in get_team_variants(row["AwayTeam"])]
    if any(v in label_norm for v in home_variants):
        return "H"
    if any(v in label_norm for v in away_variants):
        return "A"
    if "draw" in label_norm or "tie" in label_norm:
        return "D"
    return None


# ─────────────────────────────────────────────
# ERGEBNIS-INFERENZ
# ─────────────────────────────────────────────

def infer_binary_yes_no(market):
    winners = [normalize_text(x) for x in get_resolved_winning_outcomes(market)]
    if any(x == "yes" for x in winners):
        return True
    if any(x == "no" for x in winners):
        return False
    outcome_prices = parse_json_field(market.get("outcomePrices"))
    outcomes       = parse_json_field(market.get("outcomes"))
    if outcomes and outcome_prices and len(outcomes) == len(outcome_prices):
        for outcome, price in zip(outcomes, outcome_prices):
            if normalize_text(outcome) == "yes" and safe_float(price) >= 0.99:
                return True
            if normalize_text(outcome) == "no" and safe_float(price) >= 0.99:
                return False
    return None


def infer_poly_result_from_full_1x2(market, row):
    for winner in get_resolved_winning_outcomes(market):
        result = classify_outcome_label(winner, row)
        if result:
            return result
    return None


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


def compare_poly_result_with_csv(best, row):
    csv_result = row.get("FTR")
    if pd.isna(csv_result):
        return None, "csv_result_missing", False
    poly_result, method = infer_poly_result_from_best(best, row)
    if poly_result is None:
        return None, method, False
    return poly_result, method, poly_result == csv_result


# ─────────────────────────────────────────────
# NEU: MAPPING QUALITY BERECHNEN
# ─────────────────────────────────────────────

def compute_mapping_quality(best, poly_resolved_result, poly_result_matches_csv, csv_result_available):
    """
    Berechnet die Mapping-Qualität basierend auf:
    - Markttyp (1x2 vs. binary)
    - Anzahl gefundener Binary-Märkte
    - Ergebnis-Verifizierung
    
    Gibt (quality_tier, quality_score) zurück:
      quality_tier: String-Label (QUALITY_* Konstanten oben)
      quality_score: Numerisch 1–5 (1 = beste, 5 = schlechteste)
    """
    market_type = best["market_type"]
    all_three   = best.get("binary_markets_all_three_found", False)

    if market_type == "full_1x2":
        if csv_result_available and poly_result_matches_csv:
            return QUALITY_VERIFIED_FULL_1X2, 1
        elif csv_result_available and poly_resolved_result is not None and not poly_result_matches_csv:
            return QUALITY_MISMATCH, 4
        else:
            return QUALITY_MATCHED_FULL_1X2, 2

    if market_type == "binary_combined":
        types_found = set(best.get("binary_markets", {}).keys())
        has_all_three = all_three or ({"H", "D", "A"} == types_found)

        if has_all_three:
            if csv_result_available and poly_result_matches_csv:
                return QUALITY_VERIFIED_BINARY_COMBINED, 1
            elif csv_result_available and poly_resolved_result is not None and not poly_result_matches_csv:
                return QUALITY_MISMATCH, 4
            else:
                return QUALITY_MATCHED_BINARY_COMBINED, 2
        else:
            if csv_result_available and poly_result_matches_csv:
                return QUALITY_PARTIAL_BINARY, 3
            elif csv_result_available and poly_resolved_result is not None and not poly_result_matches_csv:
                return QUALITY_MISMATCH, 4
            else:
                return QUALITY_PARTIAL_BINARY_UNVERIFIED, 3

    # Einzelner Binary-Markt
    if csv_result_available and poly_result_matches_csv:
        return QUALITY_PARTIAL_BINARY, 3
    elif csv_result_available and poly_resolved_result is not None and not poly_result_matches_csv:
        return QUALITY_MISMATCH, 4
    else:
        return QUALITY_SINGLE_BINARY, 4


# ─────────────────────────────────────────────
# EVENT-SCORING
# ─────────────────────────────────────────────

def score_event_against_match(row, event):
    """
    Bewertet ein Event gegen ein Spiel.
    WICHTIG: Beide Teams müssen gefunden werden (strengere Anforderung als vorher).
    """
    event_text = get_event_text(event)
    both_found, home_score, away_score = both_teams_in_text(row, event_text)

    if not both_found:
        # Strafe wenn nicht beide Teams erkannt werden
        combined_score = (home_score + away_score) / 2 * 0.5
    else:
        combined_score = (home_score + away_score) / 2

    return combined_score, home_score, away_score, both_found


# ─────────────────────────────────────────────
# HAUPTFUNKTION: BESTEN MARKT FINDEN (stark überarbeitet)
# ─────────────────────────────────────────────

def find_best_market_for_match(row, events):
    """
    Sucht den besten Markt für ein Spiel.
    
    Verbesserungen gegenüber Original:
    1. BEIDE Teams müssen im Event-Text vorkommen (strenge Filterung)
    2. Binary-Märkte werden direktional analysiert (wer gewinnt bei Yes?)
    3. Konfidenz-Score fließt in die Kandidaten-Auswahl ein
    4. Minimum-Threshold nur für Events wo BEIDE Teams erkannt wurden
    """
    full_1x2_candidates = []
    binary_candidates   = []

    for event in events:
        markets = event.get("markets", [])
        if not isinstance(markets, list):
            continue

        # Event-Ebene: Beide Teams prüfen
        event_score, home_score, away_score, both_in_event = score_event_against_match(row, event)

        for market in markets:
            if not isinstance(market, dict):
                continue
            if not market.get("closed", False):
                continue
            if not is_game_outcome_market(market):
                continue

            # Markt-Ebene: Beide Teams müssen im kombinierten Event+Markt-Text vorkommen
            market_text = get_combined_event_market_text(event, market)
            both_in_market, market_home_score, market_away_score = both_teams_in_text(row, market_text)

            # Verwende den besten Score aus Event-Ebene und Markt-Ebene
            effective_home_score = max(home_score, market_home_score)
            effective_away_score = max(away_score, market_away_score)
            effective_both_found = both_in_event or both_in_market
            effective_combined   = (effective_home_score + effective_away_score) / 2

            # STRENGE FILTERUNG: Wenn nicht beide Teams irgendwo gefunden wurden → überspringen
            if not effective_both_found:
                continue

            if effective_combined < MATCH_THRESHOLD:
                continue

            volume         = get_market_volume(market)
            outcomes_tokens = get_market_outcomes_and_tokens(market)

            # Versuche 1X2-Klassifizierung
            outcome_map = {}
            for outcome_label, token_id in outcomes_tokens:
                outcome_type = classify_outcome_label(outcome_label, row)
                if outcome_type:
                    outcome_map[outcome_type] = {
                        "label":    outcome_label,
                        "token_id": token_id,
                    }

            if all(x in outcome_map for x in ["H", "D", "A"]):
                full_1x2_candidates.append({
                    "event":        event,
                    "market":       market,
                    "market_type":  "full_1x2",
                    "outcome_map":  outcome_map,
                    "event_score":  effective_combined,
                    "home_score":   effective_home_score,
                    "away_score":   effective_away_score,
                    "home_found":   True,
                    "away_found":   True,
                    "volume":       volume,
                    "binary_markets_all_three_found": False,
                    "binary_market_types_found":      None,
                    "binary_confidence": 3,  # 1X2 ist immer maximal konfident
                })
            else:
                # Direktionale Binary-Analyse
                binary_type, confidence = classify_binary_market_directional(market, row)
                yes_token = get_yes_token_id(market)

                if binary_type and yes_token and confidence >= 1:
                    binary_candidates.append({
                        "event":        event,
                        "market":       market,
                        "market_type":  "binary",
                        "binary_type":  binary_type,
                        "yes_token_id": yes_token,
                        "event_score":  effective_combined,
                        "home_score":   effective_home_score,
                        "away_score":   effective_away_score,
                        "home_found":   True,
                        "away_found":   True,
                        "volume":       volume,
                        "binary_markets_all_three_found": False,
                        "binary_market_types_found":      binary_type,
                        "binary_confidence": confidence,
                    })

    # ── Beste Kandidaten auswählen ──

    if full_1x2_candidates:
        # Bevorzuge hohen Event-Score, dann Volumen
        return max(full_1x2_candidates, key=lambda x: (x["event_score"], x["volume"]))

    if binary_candidates:
        # Gruppiere nach Outcome-Typ, wähle pro Typ den Kandidaten mit höchster Konfidenz, dann Volumen
        best_by_type = {}
        for candidate in binary_candidates:
            otype = candidate["binary_type"]
            if otype not in best_by_type:
                best_by_type[otype] = candidate
            else:
                existing = best_by_type[otype]
                # Bevorzuge höhere Konfidenz, dann höheres Volumen
                if (candidate["binary_confidence"], candidate["volume"]) > \
                   (existing["binary_confidence"],  existing["volume"]):
                    best_by_type[otype] = candidate

        if len(best_by_type) >= 2:
            binary_market_types_found   = sorted(best_by_type.keys())
            binary_markets_all_three    = all(x in best_by_type for x in ["H", "D", "A"])
            min_confidence              = min(x["binary_confidence"] for x in best_by_type.values())

            return {
                "market_type":   "binary_combined",
                "event":         list(best_by_type.values())[0]["event"],
                "market":        None,
                "binary_markets": best_by_type,
                "volume":        sum(x["volume"] for x in best_by_type.values()),
                "event_score":   max(x["event_score"] for x in best_by_type.values()),
                "home_score":    max(x["home_score"]  for x in best_by_type.values()),
                "away_score":    max(x["away_score"]  for x in best_by_type.values()),
                "home_found":    True,
                "away_found":    True,
                "binary_markets_all_three_found": binary_markets_all_three,
                "binary_market_types_found":      ",".join(binary_market_types_found),
                "binary_confidence": min_confidence,
            }

        # Einzelner Binary-Markt (niedrigste Qualitätsstufe)
        return max(binary_candidates, key=lambda x: (x["binary_confidence"], x["volume"]))

    return None


# ─────────────────────────────────────────────
# DATUM / DATEN LADEN
# ─────────────────────────────────────────────

def make_match_datetime_utc(row):
    date_str = row["Date"].strftime("%Y-%m-%d")
    time_str = str(row["Time"]) if "Time" in row and pd.notna(row["Time"]) else "15:00"
    local_dt = pd.to_datetime(f"{date_str} {time_str}", errors="coerce")
    if pd.isna(local_dt):
        return None
    local_dt = local_dt.to_pydatetime().replace(tzinfo=ZoneInfo("Europe/London"))
    return local_dt.astimezone(ZoneInfo("UTC"))


def load_football_data(source, number_of_games=None):
    df = pd.read_csv(source["url"])
    df["Date"] = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce")
    df = df.dropna(subset=["Date", "HomeTeam", "AwayTeam"])
    if "Time" not in df.columns:
        df["Time"] = "15:00"
    df = df.sort_values(["Date", "Time"])
    df["country"]    = source["country"]
    df["league"]     = source["league"]
    df["season"]     = source["season"]
    df["source_url"] = source["url"]
    if number_of_games is not None:
        return df.head(number_of_games)
    return df


MAX_RETRIES = 5
RETRY_BACKOFF_BASE = 3  # Sekunden: 3, 6, 12, 24, 48


def request_with_retry(url, params, timeout=20):
    """
    GET-Request mit exponentiellem Backoff bei Verbindungsfehlern oder Rate-Limiting.
    Versucht es bis zu MAX_RETRIES Mal, bevor ein Fehler geworfen wird.
    """
    for attempt in range(MAX_RETRIES):
        try:
            response = requests.get(url, params=params, timeout=timeout)

            # 429 = Rate-Limit → kurz warten, dann retry
            if response.status_code == 429:
                wait = RETRY_BACKOFF_BASE * (2 ** attempt)
                print(f"  Rate-Limit (429), warte {wait}s (Versuch {attempt + 1}/{MAX_RETRIES})...")
                time.sleep(wait)
                continue

            response.raise_for_status()
            return response

        except (requests.exceptions.ConnectionError,
                requests.exceptions.Timeout) as e:
            wait = RETRY_BACKOFF_BASE * (2 ** attempt)
            if attempt < MAX_RETRIES - 1:
                print(f"  Verbindungsfehler: {e.__class__.__name__}, warte {wait}s (Versuch {attempt + 1}/{MAX_RETRIES})...")
                time.sleep(wait)
            else:
                print(f"  Verbindungsfehler nach {MAX_RETRIES} Versuchen, gebe auf.")
                raise

    raise requests.exceptions.ConnectionError(f"Request fehlgeschlagen nach {MAX_RETRIES} Versuchen.")


def fetch_events_for_match(kickoff_utc):
    start = kickoff_utc - pd.Timedelta(hours=DATE_WINDOW_HOURS)
    end   = kickoff_utc + pd.Timedelta(hours=DATE_WINDOW_HOURS)
    all_events = []
    limit, offset = 100, 0

    while offset < 500:
        params = {
            "closed":        "true",
            "limit":         limit,
            "offset":        offset,
            "end_date_min":  start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end_date_max":  end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        response = request_with_retry(POLYMARKET_EVENTS_URL, params)
        events = response.json()
        if not events:
            break
        all_events.extend(events)
        if len(events) < limit:
            break
        offset += limit

    return all_events


def get_price_5_min_before_kickoff(token_id, kickoff_utc):
    target_ts = int(kickoff_utc.timestamp()) - PRICE_MINUTES_BEFORE_KICKOFF * 60
    params = {
        "market":   token_id,
        "startTs":  target_ts - 60 * 60,
        "endTs":    target_ts + 60,
        "fidelity": 1,
    }
    response = request_with_retry(POLYMARKET_PRICE_HISTORY_URL, params)
    data    = response.json()
    history = data.get("history", [])
    if not history:
        return None, None
    before_target = [p for p in history if int(p["t"]) <= target_ts]
    chosen = max(before_target, key=lambda x: int(x["t"])) if before_target \
             else min(history, key=lambda x: abs(int(x["t"]) - target_ts))
    price    = float(chosen["p"])
    price_ts = pd.to_datetime(int(chosen["t"]), unit="s", utc=True)
    return price, price_ts


# ─────────────────────────────────────────────
# LEERER RESULT-EINTRAG
# ─────────────────────────────────────────────

def empty_result(row, kickoff_utc):
    return {
        # ── CSV-Daten ──────────────────────────────────────────
        "country":      row.get("country"),
        "league":       row.get("league"),
        "season":       row.get("season"),
        "csv_date":     row["Date"],
        "csv_time":     row["Time"],
        "home_team":    row["HomeTeam"],
        "away_team":    row["AwayTeam"],
        "kickoff_utc":  kickoff_utc,
        "home_goals":   row.get("FTHG"),
        "away_goals":   row.get("FTAG"),
        "result":       row.get("FTR"),

        # ── Polymarket-Zuordnung ───────────────────────────────
        "polymarket_event_id":         None,
        "polymarket_event_title":      None,
        "polymarket_event_slug":       None,
        "polymarket_url":              None,
        "polymarket_match_type":       None,
        "polymarket_market_ids":       None,
        "polymarket_market_questions": None,
        "polymarket_market_slugs":     None,
        "market_volume":               None,

        # ── Preise ────────────────────────────────────────────
        "poly_home_price_5min": None,
        "poly_draw_price_5min": None,
        "poly_away_price_5min": None,
        "price_source_home":    None,
        "price_source_draw":    None,
        "price_source_away":    None,

        # ── Matching-Qualität ──────────────────────────────────
        "binary_markets_all_three_found": False,
        "binary_market_types_found":      None,
        "binary_confidence":              None,
        "event_score":                    None,
        "home_score":                     None,
        "away_score":                     None,
        "poly_resolved_result":           None,
        "poly_result_check_method":       None,
        "poly_result_matches_csv":        False,
        "mapping_quality":                QUALITY_NO_MARKET,
        "mapping_quality_score":          5,
    }


# ─────────────────────────────────────────────
# USER INPUT
# ─────────────────────────────────────────────

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


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

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

            # ── Ergebnis-Verifikation ──
            poly_resolved_result, poly_result_check_method, poly_result_matches_csv = \
                compare_poly_result_with_csv(best, row)

            csv_result_available = not pd.isna(row.get("FTR"))

            mapping_quality, mapping_quality_score = compute_mapping_quality(
                best, poly_resolved_result, poly_result_matches_csv, csv_result_available
            )

            # ── Preise abrufen ──
            # Jeder Preis wird explizit dem outcome_type zugeordnet.
            # price_source_* protokolliert den Markttitel zur Verifikation.
            price_home = price_draw = price_away = None
            odds_home  = odds_draw  = odds_away  = None
            price_ts_home = price_ts_draw = price_ts_away = None
            price_source_home = price_source_draw = price_source_away = None

            # Geordnete Listen für die CSV-Felder (Reihenfolge: H, D, A)
            market_ids_ordered       = {"H": None, "D": None, "A": None}
            market_questions_ordered = {"H": None, "D": None, "A": None}
            market_slugs_ordered     = {"H": None, "D": None, "A": None}

            def fetch_price_safe(token_id):
                try:
                    return get_price_5_min_before_kickoff(token_id, kickoff_utc)
                except Exception:
                    return None, None

            def price_to_odds(price):
                return 1 / price if price and price > 0 else None

            def assign_price(outcome_type, price, price_ts, market_label):
                """Weist Preis und Zeitstempel dem korrekten Ausgang zu."""
                nonlocal price_home, price_draw, price_away
                nonlocal odds_home,  odds_draw,  odds_away
                nonlocal price_ts_home, price_ts_draw, price_ts_away
                nonlocal price_source_home, price_source_draw, price_source_away
                odds = price_to_odds(price)
                if outcome_type == "H":
                    price_home, odds_home, price_ts_home = price, odds, price_ts
                    price_source_home = market_label
                elif outcome_type == "D":
                    price_draw, odds_draw, price_ts_draw = price, odds, price_ts
                    price_source_draw = market_label
                elif outcome_type == "A":
                    price_away, odds_away, price_ts_away = price, odds, price_ts
                    price_source_away = market_label

            if best["market_type"] == "full_1x2":
                market      = best["market"]
                outcome_map = best["outcome_map"]
                market_ids_ordered["H"]       = market.get("id")
                market_ids_ordered["D"]       = market.get("id")
                market_ids_ordered["A"]       = market.get("id")
                market_questions_ordered["H"] = market.get("question")
                market_questions_ordered["D"] = market.get("question")
                market_questions_ordered["A"] = market.get("question")
                market_slugs_ordered["H"]     = market.get("slug")
                market_slugs_ordered["D"]     = market.get("slug")
                market_slugs_ordered["A"]     = market.get("slug")

                for outcome_type, info in outcome_map.items():
                    # Outcome-Label aus dem Markt (z.B. "Real Madrid", "Draw", "Barcelona")
                    label = f"{market.get('question', '')} → Outcome: {info['label']}"
                    price, price_ts = fetch_price_safe(info["token_id"])
                    assign_price(outcome_type, price, price_ts, label)

            elif best["market_type"] == "binary_combined":
                for outcome_type, candidate in best["binary_markets"].items():
                    market   = candidate["market"]
                    token_id = candidate["yes_token_id"]
                    market_ids_ordered[outcome_type]       = market.get("id")
                    market_questions_ordered[outcome_type] = market.get("question")
                    market_slugs_ordered[outcome_type]     = market.get("slug")

                    label = f"{market.get('question', '')} [YES={outcome_type}]"
                    price, price_ts = fetch_price_safe(token_id)
                    assign_price(outcome_type, price, price_ts, label)

            else:  # einzelner Binary-Markt
                market       = best["market"]
                outcome_type = best["binary_type"]
                token_id     = best["yes_token_id"]
                market_ids_ordered[outcome_type]       = market.get("id")
                market_questions_ordered[outcome_type] = market.get("question")
                market_slugs_ordered[outcome_type]     = market.get("slug")

                label = f"{market.get('question', '')} [YES={outcome_type}]"
                price, price_ts = fetch_price_safe(token_id)
                assign_price(outcome_type, price, price_ts, label)

            # CSV-Felder als geordnete Strings (H | D | A)
            def ordered_str(d):
                parts = [str(d[k]) for k in ["H", "D", "A"] if d[k] is not None]
                return " | ".join(parts) if parts else None

            print(f"Event:           {event.get('title')}")
            print(f"Typ:             {best['market_type']}")
            print(f"Konfidenz:       {best.get('binary_confidence', 'n/a')}")
            print(f"Markt H:         {market_questions_ordered['H']}")
            print(f"Markt D:         {market_questions_ordered['D']}")
            print(f"Markt A:         {market_questions_ordered['A']}")
            print(f"Home price:      {price_home} (Quelle: {price_source_home})")
            print(f"Draw price:      {price_draw} (Quelle: {price_source_draw})")
            print(f"Away price:      {price_away} (Quelle: {price_source_away})")
            print(f"CSV Ergebnis:    {row.get('FTR')}")
            print(f"Poly Ergebnis:   {poly_resolved_result}")
            print(f"Mapping Quality: {mapping_quality} (Score {mapping_quality_score})")

            results.append({
                # ── CSV-Daten ──────────────────────────────────────────
                "country":      row.get("country"),
                "league":       row.get("league"),
                "season":       row.get("season"),
                "csv_date":     row["Date"],
                "csv_time":     row["Time"],
                "home_team":    row["HomeTeam"],
                "away_team":    row["AwayTeam"],
                "kickoff_utc":  kickoff_utc,
                "home_goals":   row.get("FTHG"),
                "away_goals":   row.get("FTAG"),
                "result":       row.get("FTR"),

                # ── Polymarket-Zuordnung ───────────────────────────────
                "polymarket_event_id":       event.get("id"),
                "polymarket_event_title":    event.get("title"),
                "polymarket_event_slug":     event.get("slug"),
                "polymarket_url":            f"https://polymarket.com/event/{event.get('slug')}" if event.get("slug") else None,
                "polymarket_match_type":     best["market_type"],
                "polymarket_market_ids":     ordered_str(market_ids_ordered),
                "polymarket_market_questions": ordered_str(market_questions_ordered),
                "polymarket_market_slugs":   ordered_str(market_slugs_ordered),
                "market_volume":             best["volume"],

                # ── Preise (Wahrscheinlichkeit 0–1) ───────────────────
                # Wichtig: home/draw/away beziehen sich auf Heim/Unentschieden/Auswärts
                # aus der CSV, nicht auf die Reihenfolge der Polymarket-Outcomes!
                "poly_home_price_5min":  price_home,
                "poly_draw_price_5min":  price_draw,
                "poly_away_price_5min":  price_away,

                # Zur Nachvollziehbarkeit: welcher Markt lieferte welchen Preis?
                "price_source_home":     price_source_home,
                "price_source_draw":     price_source_draw,
                "price_source_away":     price_source_away,

                # ── Matching-Qualität ──────────────────────────────────
                "binary_markets_all_three_found": best.get("binary_markets_all_three_found", False),
                "binary_market_types_found":      best.get("binary_market_types_found"),
                "binary_confidence":              best.get("binary_confidence"),
                "event_score":                    best["event_score"],
                "home_score":                     best["home_score"],
                "away_score":                     best["away_score"],
                "poly_resolved_result":           poly_resolved_result,
                "poly_result_check_method":       poly_result_check_method,
                "poly_result_matches_csv":        poly_result_matches_csv,
                "mapping_quality":                mapping_quality,
                "mapping_quality_score":          mapping_quality_score,
            })

            time.sleep(0.2)

        result_df = pd.DataFrame(results)
        result_df.to_csv(OUTPUT_FILE, index=False)
        print(f"\nGespeichert als: {OUTPUT_FILE}")

    # ── Zusammenfassung der Mapping-Qualitäten ──
    result_df = pd.DataFrame(results)
    print("\n══════════════════════════════════════════")
    print("MAPPING QUALITY ÜBERSICHT")
    print("══════════════════════════════════════════")
    if not result_df.empty and "mapping_quality" in result_df.columns:
        summary = result_df["mapping_quality"].value_counts().sort_index()
        for quality, count in summary.items():
            print(f"  {quality}: {count} Spiele")
        tier1 = result_df[result_df["mapping_quality_score"] <= 2]
        print(f"\n→ Für Analyse empfohlen (Score 1-2): {len(tier1)} Spiele")
    print("══════════════════════════════════════════")


if __name__ == "__main__":
    main()