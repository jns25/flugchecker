#!/usr/bin/env python3
"""
Flugchecker: STR -> PMI Preisüberwachung
Datenquelle: Google Flights via fast_flights (kein API-Key, alle Airlines)

Strategie: Rollierender Scan der naechsten Wochen.
  - Wochenenden (Fr/Sa Abflug) fuer die naechsten 8 Wochen
  - Zusaetzlich naechste 14 Tage komplett (Last Minute)
  - Aufenthaltsdauer 1-3 Tage
  - Pro Lauf werden die N guenstigsten Datumskombinationen gesucht

Verwendung:
  python check_flights.py summary   -> Tagesupdate: beste Deals der naechsten Wochen
  python check_flights.py alert     -> Alert wenn irgendein Deal unter PRICE_THRESHOLD faellt

GitHub Secrets:   TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
GitHub Variables: PRICE_THRESHOLD (z.B. 150)
"""

import os
import re
import sys
import time
import requests
from datetime import date, timedelta, datetime, timezone
from fast_flights import get_flights, FlightData, Passengers

# --- Konfiguration -----------------------------------------------------------

TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
PRICE_THRESHOLD  = float(os.environ.get("PRICE_THRESHOLD") or "150")

# Suchparameter (in Code aenderbar, keine Variable noetig)
SEARCH_WEEKS_AHEAD = 10     # Wie viele Wochen vorausschauen
LAST_MINUTE_DAYS   = 14     # Zusaetzlich alle Tage innerhalb dieser Tage
MIN_TRIP_DAYS      = 1      # Minimale Aufenthaltsdauer
MAX_TRIP_DAYS      = 3      # Maximale Aufenthaltsdauer
MAX_SEARCHES       = 15     # Max. Google-Flights-Abfragen pro Lauf

MODE = sys.argv[1] if len(sys.argv) > 1 else "summary"

ORIGIN      = "STR"
DESTINATION = "PMI"


# --- Validierung -------------------------------------------------------------

def validate_config():
    missing = [v for v in ["TELEGRAM_TOKEN", "TELEGRAM_CHAT_ID"]
               if not os.environ.get(v)]
    if missing:
        print(f"FEHLER: Fehlende Umgebungsvariablen: {', '.join(missing)}")
        sys.exit(1)


# --- Datumsgenerierung -------------------------------------------------------

def generate_date_pairs(mode="summary"):
    """
    Generiert priorisierte (outbound, return) Datumspaare.

    Logik:
      - Naechste SEARCH_WEEKS_AHEAD Wochen: Fr + Sa Abfluege (Wochenend-Trips)
      - Naechste LAST_MINUTE_DAYS Tage: alle Wochentage (Last Minute)
      - Pro Outbound-Datum: alle Aufenthaltsdauern von MIN bis MAX Tage
      - Wochenenden zuerst sortiert, dann chronologisch
      - Auf MAX_SEARCHES begrenzt
    """
    today = date.today()
    seen_pairs = set()
    candidates = []

    days_ahead = SEARCH_WEEKS_AHEAD * 7

    for i in range(1, days_ahead + 1):
        out_date = today + timedelta(days=i)
        weekday  = out_date.weekday()  # 0=Mo ... 4=Fr, 5=Sa, 6=So

        is_weekend_dep  = weekday in (4, 5)        # Fr oder Sa
        is_last_minute  = i <= LAST_MINUTE_DAYS

        if not (is_weekend_dep or is_last_minute):
            continue

        for duration in range(MIN_TRIP_DAYS, MAX_TRIP_DAYS + 1):
            ret_date = out_date + timedelta(days=duration)
            key = (out_date, ret_date)
            if key in seen_pairs:
                continue
            seen_pairs.add(key)

            ret_weekday = ret_date.weekday()
            is_weekend_ret = ret_weekday in (5, 6)  # Sa oder So

            # Score: niedrig = besser
            # Wochenende Hin + Wochenende Rueck = Score 0
            # Nur Wochenende Hin = Score 1
            # Last Minute = Score 2
            if is_weekend_dep and is_weekend_ret:
                score = 0
            elif is_weekend_dep:
                score = 1
            elif is_last_minute:
                score = 2
            else:
                score = 3

            candidates.append({
                "outbound":    out_date,
                "return":      ret_date,
                "days_ahead":  i,
                "duration":    duration,
                "is_weekend":  is_weekend_dep,
                "score":       score,
            })

    # Sortieren: Score (Wochenende zuerst), dann Datum
    candidates.sort(key=lambda x: (x["score"], x["days_ahead"]))

    limit = MAX_SEARCHES
    return candidates[:limit]


# --- Flugsuche ---------------------------------------------------------------

def search_all_flights(mode="summary"):
    """
    Sucht fuer alle generierten Datumspaare und gibt das guenstigste
    Angebot pro Datumspaar zurueck, sortiert nach Preis.
    """
    pairs   = generate_date_pairs(mode)
    results = []

    print(f"Suche in {len(pairs)} Datumskombinationen...")

    for pair in pairs:
        out_str = pair["outbound"].strftime("%Y-%m-%d")
        ret_str = pair["return"].strftime("%Y-%m-%d")
        print(f"  {out_str} -> {ret_str} ({pair['duration']} Tage)...", end=" ", flush=True)

        try:
            result = get_flights(
                flight_data=[
                    FlightData(date=out_str, from_airport=ORIGIN,      to_airport=DESTINATION),
                    FlightData(date=ret_str, from_airport=DESTINATION, to_airport=ORIGIN),
                ],
                trip="round-trip",
                seat="economy",
                passengers=Passengers(adults=1),
            )

            # Guengstigstes Angebot fuer dieses Datumspaar
            best = None
            for flight in result.flights:
                price = parse_price(flight.price)
                if price is not None:
                    if best is None or price < best["price"]:
                        best = {
                            "price":        price,
                            "flight":       flight,
                            "outbound":     pair["outbound"],
                            "return":       pair["return"],
                            "duration":     pair["duration"],
                            "is_weekend":   pair["is_weekend"],
                            "market":       result.current_price,
                        }

            if best:
                results.append(best)
                print(f"{best['price']:.0f}EUR")
            else:
                print("keine Ergebnisse")

        except Exception as e:
            print(f"Fehler: {e}")

        time.sleep(0.8)  # Google nicht ueberlasten

    # Gesamtergebnis nach Preis sortieren
    results.sort(key=lambda x: x["price"])
    return results


# --- Hilfsfunktionen ---------------------------------------------------------

def parse_price(price_str):
    """Extrahiert float aus '€89', '1.234 €', '89,50 EUR' etc."""
    if not price_str:
        return None
    cleaned = re.sub(r"[^\d.,]", "", price_str).replace(",", ".")
    parts = cleaned.split(".")
    if len(parts) > 2:
        cleaned = "".join(parts[:-1]) + "." + parts[-1]
    elif len(parts) == 2 and len(parts[1]) == 3:
        cleaned = "".join(parts)
    try:
        return float(cleaned)
    except ValueError:
        return None


def stops_label(n):
    try:
        n = int(n)
    except (ValueError, TypeError):
        return str(n)
    return "direkt" if n == 0 else f"{n} Stopp{'s' if n > 1 else ''}"


def weekday_de(d):
    names = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
    return names[d.weekday()]


def format_deal(deal, rank=None):
    """Formatiert einen Deal als Telegram-Markdown-Block."""
    f        = deal["flight"]
    price    = deal["price"]
    out_date = deal["outbound"]
    ret_date = deal["return"]
    dur      = deal["duration"]
    market   = deal["market"]

    prefix       = f"#{rank} " if rank else ""
    market_emoji = {"low": "🟢", "typical": "🟡", "high": "🔴"}.get(market, "⚪")
    weekend_tag  = " 🏖" if deal["is_weekend"] else ""
    ahead        = f" (+{f.arrival_time_ahead})" if f.arrival_time_ahead else ""
    delay        = f"\n  ⚠️ {f.delay}" if f.delay else ""

    lines = [
        f"{prefix}*{price:.0f}€* – {f.name}  {market_emoji}{weekend_tag}",
        f"  📅 {weekday_de(out_date)} {out_date.strftime('%d.%m.')} -> "
        f"{weekday_de(ret_date)} {ret_date.strftime('%d.%m.')}  ({dur} {'Tag' if dur == 1 else 'Tage'})",
        f"  ✈️ Abflug: {f.departure}  |  Ankunft: {f.arrival}{ahead}",
        f"  ⏱ {f.duration}  |  {stops_label(f.stops)}{delay}",
    ]
    return "\n".join(lines)


# --- Telegram ----------------------------------------------------------------

def send_telegram(message):
    resp = requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json={
            "chat_id":                  TELEGRAM_CHAT_ID,
            "text":                     message,
            "parse_mode":               "Markdown",
            "disable_web_page_preview": True,
        },
        timeout=15,
    )
    resp.raise_for_status()
    print(f"OK: Telegram gesendet ({len(message)} Zeichen)")


# --- Modus: Tagesupdate ------------------------------------------------------

def run_summary():
    print("Modus: Tagesupdate")
    deals   = search_all_flights("summary")
    now_str = datetime.now(tz=timezone.utc).strftime("%d.%m.%Y")

    if not deals:
        send_telegram(
            f"🔍 *Flugchecker {now_str}*\n"
            f"Keine Flüge STR -> PMI in den nächsten {SEARCH_WEEKS_AHEAD} Wochen gefunden."
        )
        return

    cheapest = deals[0]["price"]
    top5     = deals[:5]

    header = [
        f"🌅 *Flugchecker – Tagesupdate {now_str}*",
        f"STR -> PMI -> STR  |  1 Person  |  Wochenenden + Last Minute",
        f"Aufenthalt 1-3 Tage  |  nächste {SEARCH_WEEKS_AHEAD} Wochen  |  Alle Airlines\n",
    ]
    body = []
    for i, deal in enumerate(top5, 1):
        body.append(format_deal(deal, rank=i))
        body.append("")

    footer = []
    if cheapest < PRICE_THRESHOLD:
        footer.append(
            f"🚨 *GÜNSTIG!* {cheapest:.0f}€ liegt unter deinem Limit von {PRICE_THRESHOLD:.0f}€!"
        )

    send_telegram("\n".join(header + body + footer))


# --- Modus: Preis-Alert ------------------------------------------------------

def run_alert():
    print(f"Modus: Preis-Alert (Limit: {PRICE_THRESHOLD:.0f}€)")
    deals = search_all_flights("alert")

    if not deals:
        print("Keine Deals gefunden.")
        return

    best = deals[0]
    print(f"Guenstigster Deal: {best['price']:.0f}EUR "
          f"({best['outbound']} -> {best['return']})")

    if best["price"] < PRICE_THRESHOLD:
        print("-> Alert wird gesendet!")
        lines = [
            f"🚨 *PREIS-ALERT! Günstiger Deal gefunden:*\n",
            format_deal(best),
            f"\n📉 *{best['price']:.0f}€* liegt unter deinem Limit von *{PRICE_THRESHOLD:.0f}€*",
        ]
        if len(deals) > 1:
            lines.append("\n*Weitere günstige Optionen:*")
            for d in deals[1:4]:
                wd_out = weekday_de(d["outbound"])
                lines.append(
                    f"• {d['price']:.0f}€ – {d['flight'].name}  "
                    f"({wd_out} {d['outbound'].strftime('%d.%m.')} / {d['duration']} Tage)"
                )

        send_telegram("\n".join(lines))

        with open("alert_triggered.txt", "w") as fh:
            fh.write(f"{best['price']:.2f}\n{datetime.now(tz=timezone.utc).isoformat()}\n")
        print("alert_triggered.txt geschrieben (GitHub Cooldown)")
    else:
        print(f"Kein Alert: {best['price']:.0f}€ >= {PRICE_THRESHOLD:.0f}€")


# --- Entry Point -------------------------------------------------------------

if __name__ == "__main__":
    validate_config()
    if MODE == "summary":
        run_summary()
    elif MODE == "alert":
        run_alert()
    else:
        print(f"Unbekannter Modus: '{MODE}'. Verwende 'summary' oder 'alert'.")
        sys.exit(1)
