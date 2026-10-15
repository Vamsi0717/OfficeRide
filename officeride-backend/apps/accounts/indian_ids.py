"""Checks for Indian vehicle registration numbers and driving licence numbers. Pure Python, no Django.

Bangalore sees vehicles from every state, so every state and union territory code is accepted,
not only KA. These are format checks: they stop typing mistakes, they do not prove the document
is real. An admin still reads the uploaded file before approving it.
"""

import re
from datetime import date

# State and union territory codes used on registration plates and licences.
STATE_CODES = {
    "AN": "Andaman and Nicobar", "AP": "Andhra Pradesh", "AR": "Arunachal Pradesh", "AS": "Assam",
    "BR": "Bihar", "CG": "Chhattisgarh", "CH": "Chandigarh", "CT": "Chhattisgarh (old)",
    "DD": "Daman and Diu", "DL": "Delhi", "DN": "Dadra and Nagar Haveli", "GA": "Goa", "GJ": "Gujarat",
    "HP": "Himachal Pradesh", "HR": "Haryana", "JH": "Jharkhand", "JK": "Jammu and Kashmir",
    "KA": "Karnataka", "KL": "Kerala", "LA": "Ladakh", "LD": "Lakshadweep", "MH": "Maharashtra",
    "ML": "Meghalaya", "MN": "Manipur", "MP": "Madhya Pradesh", "MZ": "Mizoram", "NL": "Nagaland",
    "OD": "Odisha", "OR": "Odisha (old)", "PB": "Punjab", "PY": "Puducherry", "RJ": "Rajasthan",
    "SK": "Sikkim", "TG": "Telangana", "TN": "Tamil Nadu", "TR": "Tripura", "TS": "Telangana (old)",
    "UA": "Uttarakhand (old)", "UK": "Uttarakhand", "UP": "Uttar Pradesh", "WB": "West Bengal",
}

# State code, 1 or 2 digit RTO number, 1 to 3 series letters, 1 to 4 digit number: KA01AB1234, DL8CAF5030, MH12DE1433.
_RC = re.compile(r"^([A-Z]{2})(\d{1,2})([A-Z]{0,3})(\d{1,4})$")
# Bharat series plates: 22BH1234AA.
_BH = re.compile(r"^(\d{2})BH(\d{4})([A-Z]{1,2})$")
# State code, 2 digit RTO code, 4 digit year of issue, 7 digit serial: KA0120110012345.
_LICENCE = re.compile(r"^([A-Z]{2})(\d{2})(\d{4})(\d{7})$")


def _squash(raw):
    return re.sub(r"[\s-]", "", (raw or "")).upper()


def normalise_rc(raw):
    """Returns the registration number without spaces, e.g. 'ka 01 ab 1234' -> 'KA01AB1234'. Raises ValueError."""
    value = _squash(raw)
    if _BH.match(value):
        return value
    m = _RC.match(value)
    if not m:
        raise ValueError("Enter the registration number as printed on the RC, for example KA01AB1234.")
    state, rto, _series, number = m.groups()
    if state not in STATE_CODES:
        raise ValueError(f"{state} is not an Indian state code. Check the first two letters of the RC number.")
    if int(rto) == 0:
        raise ValueError("The RTO number in the RC number cannot be 00.")
    if int(number) == 0:
        raise ValueError("The last digits of the RC number cannot be 0000.")
    return value


def normalise_licence(raw, today=None):
    """Returns the licence number without spaces, e.g. 'KA01 20110012345' -> 'KA0120110012345'. Raises ValueError."""
    value = _squash(raw)
    m = _LICENCE.match(value)
    if not m:
        raise ValueError(
            "Enter the licence number as printed on your licence: state code, 2 digit RTO code, "
            "4 digit year and 7 digits, for example KA01 20110012345."
        )
    state, rto, year, _serial = m.groups()
    if state not in STATE_CODES:
        raise ValueError(f"{state} is not an Indian state code. Check the first two letters of the licence number.")
    if int(rto) == 0:
        raise ValueError("The RTO code in the licence number cannot be 00.")
    today = today or date.today()
    if not (1950 <= int(year) <= today.year):
        raise ValueError("The year in the licence number does not look right.")
    return value


def pretty_rc(value):
    """KA01AB1234 -> 'KA 01 AB 1234' for showing. Anything that does not fit is returned unchanged."""
    m = _RC.match(value or "")
    return " ".join(p for p in m.groups() if p) if m else (value or "")


def pretty_licence(value):
    """KA0120110012345 -> 'KA01 20110012345' for showing. Anything that does not fit is returned unchanged."""
    m = _LICENCE.match(value or "")
    return f"{m.group(1)}{m.group(2)} {m.group(3)}{m.group(4)}" if m else (value or "")