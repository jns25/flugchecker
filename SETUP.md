# Flugchecker – Setup-Anleitung

STR -> PMI Preisüberwachung | Alle Airlines | Kostenlos | 24/7 | Telegram-Alerts

---

## Überblick

| Komponente | Tool | Kosten | Konfiguration |
|---|---|---|---|
| Flugdaten | Google Flights (via fast_flights) | kostenlos | kein API-Key nötig |
| Automatisierung | GitHub Actions | kostenlos | public Repo |
| Benachrichtigungen | Telegram Bot | kostenlos | Bot-Token |

Was passiert automatisch:
- Jeden Morgen ~08:00 Uhr MEZ: Telegram mit den 5 günstigsten Deals der nächsten Wochen
- Alle 30 Minuten: stille Prüfung; Alert wenn ein Deal unter dein Preislimit fällt (max. 1x pro 4h)

Suchstrategie:
- Wochenenden (Fr/Sa Abflug, Sa/So Rückflug) für die nächsten 10 Wochen
- Zusätzlich alle Tage innerhalb der nächsten 14 Tage (Last Minute)
- Aufenthaltsdauer 1-3 Tage
- Alle Airlines (Ryanair, Eurowings, Wizz Air, Condor, ...)

---

## Schritt 1: Telegram Bot erstellen (~5 Min)

1. Öffne Telegram und suche nach @BotFather
2. Schreibe `/newbot`
3. Gib einen Namen und einen Username ein (muss auf `_bot` enden)
4. BotFather gibt dir einen Token: `123456789:ABCdefGHI...` -> kopieren

Chat-ID herausfinden:
1. Schreibe deinem neuen Bot irgendeine Nachricht (damit er dich kennt)
2. Öffne im Browser: `https://api.telegram.org/bot<DEIN_TOKEN>/getUpdates`
3. In der JSON-Antwort findest du `"chat":{"id": 123456789}` -> das ist deine Chat-ID

---

## Schritt 2: GitHub Repository einrichten (~10 Min)

### 2a) Neues Repository erstellen

1. Gehe auf https://github.com/new
2. Name: `flugchecker` (beliebig)
3. Sichtbarkeit: PUBLIC (-> unbegrenzte GitHub Actions Minuten, kein Risiko da keine Credentials im Code)
4. "Create repository" klicken

### 2b) Dateien hochladen

Per Git (empfohlen):
```bash
git init
git add .
git commit -m "Initial: Flugchecker"
git branch -M main
git remote add origin https://github.com/DEIN_USERNAME/flugchecker.git
git push -u origin main
```

Alternativ per GitHub Web-Interface: "Add file" -> "Upload files"

---

## Schritt 3: Secrets und Variable konfigurieren (~5 Min)

Im GitHub-Repo: Settings -> Secrets and variables -> Actions

### Secrets (unter "Repository secrets")

| Name | Wert |
|---|---|
| `TELEGRAM_TOKEN` | Dein Telegram Bot Token |
| `TELEGRAM_CHAT_ID` | Deine Telegram Chat-ID |

### Variable (unter "Repository variables")

| Name | Beispielwert | Beschreibung |
|---|---|---|
| `PRICE_THRESHOLD` | `150` | Preis-Limit in EUR – darunter kommt ein gesonderter Alert |

Das war's. Keine Reisedaten nötig – der Scanner sucht selbstständig
in den nächsten Wochen nach den besten Deals.

---

## Schritt 4: Testen

1. Im Repo: Actions -> "Tägliche Flugzusammenfassung"
2. "Run workflow" -> "Run workflow" klicken
3. Job anklicken, Logs verfolgen (dauert ~60-90 Sek wegen mehrerer Suchen)
4. Telegram-Nachricht sollte ankommen

Dann dasselbe für "Preis-Alert" testen.

---

## Suchparameter anpassen (optional)

In `scripts/check_flights.py` ganz oben:

```python
SEARCH_WEEKS_AHEAD = 10   # Wie viele Wochen vorausschauen
LAST_MINUTE_DAYS   = 14   # Alle Tage innerhalb dieser Frist immer prüfen
MIN_TRIP_DAYS      = 1    # Kürzester Aufenthalt in Tagen
MAX_TRIP_DAYS      = 3    # Längster Aufenthalt in Tagen
MAX_SEARCHES       = 15   # Max. Suchen pro Lauf (mehr = langsamer aber vollständiger)
```

---

## Beispiel Telegram-Nachrichten

Tagesupdate:
```
Flugchecker – Tagesupdate 09.05.2026
STR -> PMI -> STR  |  1 Person  |  Wochenenden + Last Minute
Aufenthalt 1-3 Tage  |  nächste 10 Wochen  |  Alle Airlines

#1 *79€* – Ryanair  🟢 🏖
  📅 Fr 15.05. -> So 17.05.  (2 Tage)
  ✈️ Abflug: 06:30  |  Ankunft: 08:10
  ⏱ 1 hr 40 min  |  direkt

#2 *94€* – Eurowings  🟡 🏖
  📅 Sa 23.05. -> So 24.05.  (1 Tag)
  ...
```

Preis-Alert:
```
PREIS-ALERT! Günstiger Deal gefunden:

*69€* – Ryanair  🟢 🏖
  📅 Fr 15.05. -> So 17.05.  (2 Tage)
  ✈️ Abflug: 06:30  |  Ankunft: 08:10
  ⏱ 1 hr 40 min  |  direkt

69€ liegt unter deinem Limit von 150€!
```

Legende: 🟢 = Preis niedrig  🟡 = typisch  🔴 = hoch  🏖 = Wochenend-Abflug

---

## Kosten

| Dienst | Kosten |
|---|---|
| GitHub Actions (public repo) | 0€ / unbegrenzt |
| Google Flights via fast_flights | 0€ / kein API-Key |
| Telegram Bot API | 0€ / unbegrenzt |

---

## Troubleshooting

Script schlägt fehl mit ConnectError
-> Google Flights kurz nicht erreichbar; beim nächsten Run (30 Min) automatisch retry

Telegram-Nachricht kommt nicht an
-> Prüfe ob du dem Bot vorher eine Nachricht geschickt hast
-> TELEGRAM_CHAT_ID mit getUpdates-Aufruf verifizieren

Keine Deals gefunden
-> GitHub Actions Logs prüfen: welche Datumspaare wurden gesucht?
-> Ggf. SEARCH_WEEKS_AHEAD im Script erhöhen

GitHub Actions startet nicht automatisch
-> Beim ersten Push kann der Cron bis zu 60 Min verzögert sein
-> "Run workflow" manuell zum Testen nutzen
