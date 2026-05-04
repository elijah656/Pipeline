# Pipeline

Dateien:
polymarket_csv_creation.py erstellt bei Ausführung eine neue csv. Es werden den Spielen aus der Datei von footballdata.uk passende Märkte zugeordnet.
Bei Ausführung wird Eingabe gefordert. Wenn man nur Enter drückt und nichts eingibt, wird die ganze "footballdata.uk.csv" Datei durchgegangen. Gibt man Zahl n ein, werden den ersten n Spielen Märkte zugeordnet
Man kann weitere Quelldateien hinzufügen, wie im Beispiel Zeile 16 in polymarket_csv_creation.py

Die streamlit-Dateien dienen der graphischen Darstellung. 
streamlit_polymarket_analysis.py stellt nur polymarket Märkte graphisch dar. 
streamlit_sportsbetting_analysis.py stellt nur Sportwetten graphisch dar.

streamlit wird wie folgt in Konsole als Webanwendung gestartet (auf mac):
python -m streamlit run streamlit_polymarket_analyse.py
python -m streamlit run streamlit_sportsbetting_analyse.py


