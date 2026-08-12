"""Turn a callsign into an airline name, with no API call.

ADS-B gives you the ATC callsign, not the airline. "EXS811" is Jet2 flight 811
- the first three letters are the operator's ICAO designator. That's a lookup
table, so it costs nothing and works offline.

The list leans towards what actually shows up over West Yorkshire. Anything
not in it falls back to the raw three-letter code, which is still more useful
than nothing, and light aircraft come back as "Private / GA".
"""

from __future__ import annotations

AIRLINES = {
    # Leeds Bradford's based and regular operators
    "EXS": "Jet2",
    "RYR": "Ryanair",
    "RUK": "Ryanair UK",
    "EZY": "easyJet",
    "EJU": "easyJet Europe",
    "TOM": "TUI Airways",
    "LOG": "Loganair",
    "EZE": "Eastern Airways",
    "BAW": "British Airways",
    "SHT": "British Airways",
    "CFE": "BA CityFlyer",
    "KLM": "KLM",
    "EIN": "Aer Lingus",
    "EUK": "Aer Lingus UK",
    "WZZ": "Wizz Air",
    "WUK": "Wizz Air UK",
    "AEE": "Aegean",
    "VLG": "Vueling",
    "IBS": "Iberia Express",
    "PGT": "Pegasus",
    "SXS": "SunExpress",
    "CAI": "Corendon",
    "TCX": "Titan / Thomas Cook",
    "AWC": "Titan Airways",
    "JOS": "Jota Aviation",
    # European majors that overfly or divert in
    "DLH": "Lufthansa",
    "AFR": "Air France",
    "SWR": "Swiss",
    "AUA": "Austrian",
    "EWG": "Eurowings",
    "BEL": "Brussels Airlines",
    "SAS": "SAS",
    "NOZ": "Norwegian",
    "NSZ": "Norwegian",
    "TAP": "TAP Air Portugal",
    "IBE": "Iberia",
    "ITY": "ITA Airways",
    "LOT": "LOT",
    "ROT": "TAROM",
    "THY": "Turkish Airlines",
    "FIN": "Finnair",
    "ICE": "Icelandair",
    "AEA": "Air Europa",
    # long-haul overflights, common at 30,000ft+
    "UAE": "Emirates",
    "QTR": "Qatar Airways",
    "ETD": "Etihad",
    "SIA": "Singapore Airlines",
    "ACA": "Air Canada",
    "UAL": "United",
    "AAL": "American",
    "DAL": "Delta",
    "VIR": "Virgin Atlantic",
    "ELY": "El Al",
    "MSR": "EgyptAir",
    "ETH": "Ethiopian",
    "AIC": "Air India",
    # freight
    "BCS": "DHL (EAT Leipzig)",
    "DHK": "DHL Air UK",
    "NPT": "West Atlantic",
    "FDX": "FedEx",
    "GTI": "Atlas Air",
    "ABR": "ASL Airlines",
    # state and military
    "RRR": "Royal Air Force",
    "RCH": "US Air Mobility Command",
    "CTM": "French Air Force",
    "NAF": "Netherlands Air Force",
}


def airline_for(callsign: str) -> str:
    """Best-effort operator name for an ATC callsign."""
    cs = (callsign or "").strip().upper()
    if len(cs) < 4:
        return "Unknown"

    prefix, rest = cs[:3], cs[3:]
    # A real airline callsign is three letters then a flight number.
    # Light aircraft transmit their registration instead ("GCJKL"), which has
    # no digits after the first three characters.
    if prefix.isalpha() and any(c.isdigit() for c in rest):
        return AIRLINES.get(prefix, prefix)
    return "Private / GA"


def is_airline(callsign: str) -> bool:
    return airline_for(callsign) not in ("Unknown", "Private / GA")
