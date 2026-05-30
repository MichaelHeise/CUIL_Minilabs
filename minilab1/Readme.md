# Minilab 1

## Connection.py

Ich habe schonmal eine Pyhton Datei geschrieben, die eine high level library nutzt um die Anfragen zu schicken, die im Assignement notwedig sind.

Um sie zu nutzen empfehle ich ein virtual environment anzulegen und packages zu installieren. Falls ihr nicht wisst wie hier ein kleiner guide.
Startet ein Terminal in dem `minilab1` Folder.

```bash
# Virtual environment erstellen und Dependencies installieren
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt

# Beispiel Ausführen
python connection.py

# Parameter anzeigen lassen
python connection.py -h

# HTTP/2 nutzen
python connection.py --http_version 2
```

Das script nimmt mehere parameter entgegen sodass wir die meisten Anfragen stellen können. Anschließen kann man falls nötig das Script noch erweitern.
