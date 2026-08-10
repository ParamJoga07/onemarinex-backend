"""Canonical crew rank and nationality values used at API boundaries.

Crew profiles have always declared nationality as ISO 3166-1 alpha-2, while
manifest rows historically stored a mix of country names, demonyms and codes.
Normalising writes prevents more mixed data without hiding legacy values that
still need an explicit repair review.
"""

from typing import Optional


COUNTRY_ALIASES = {
    "BANGLADESH": "BD", "BULGARIA": "BG", "CHINA": "CN", "CHINESE": "CN",
    "CROATIA": "HR", "EGYPT": "EG", "GEORGIA": "GE", "GHANA": "GH",
    "GREECE": "GR", "INDIA": "IN", "INDIAN": "IN", "INDONESIA": "ID",
    "ITALY": "IT", "LATVIA": "LV", "MALAYSIA": "MY", "MYANMAR": "MM",
    "BURMA": "MM", "NIGERIA": "NG", "NORWAY": "NO", "PAKISTAN": "PK",
    "PANAMA": "PA", "PERU": "PE", "PHILIPPINES": "PH", "FILIPINO": "PH",
    "POLAND": "PL", "ROMANIA": "RO", "RUSSIA": "RU", "RUSSIAN FEDERATION": "RU",
    "SOUTH KOREA": "KR", "REPUBLIC OF KOREA": "KR", "KOREA": "KR",
    "SPAIN": "ES", "SRI LANKA": "LK", "TURKEY": "TR", "TURKIYE": "TR",
    "UK": "GB", "UNITED KINGDOM": "GB", "GREAT BRITAIN": "GB",
    "USA": "US", "UNITED STATES": "US", "UNITED STATES OF AMERICA": "US",
    "UKRAINE": "UA", "VIETNAM": "VN", "VIET NAM": "VN",
}


def normalize_nationality(value: Optional[str], *, strict: bool = False) -> Optional[str]:
    if value is None:
        return None
    cleaned = " ".join(str(value).strip().upper().replace(".", "").split())
    if not cleaned:
        return None
    if len(cleaned) == 2 and cleaned.isalpha():
        return cleaned
    result = COUNTRY_ALIASES.get(cleaned)
    if result:
        return result
    if strict:
        raise ValueError("Nationality must be a supported ISO alpha-2 code or country name")
    return None


RANK_ALIASES = {
    "MASTER": "captain", "CAPTAIN": "captain", "CH OFF": "chief_officer",
    "CHIEF OFFICER": "chief_officer", "2ND OFF": "second_officer",
    "SECOND OFFICER": "second_officer", "3RD OFF": "third_officer",
    "THIRD OFFICER": "third_officer", "CH ENG": "chief_engineer",
    "CHIEF ENGINEER": "chief_engineer", "2 ENG": "second_engineer",
    "SECOND ENGINEER": "second_engineer", "3 ENG": "third_engineer",
    "THIRD ENGINEER": "third_engineer", "AB": "able_seaman",
    "ABLE SEAMAN": "able_seaman", "OS": "ordinary_seaman",
    "ORDINARY SEAMAN": "ordinary_seaman", "MOTOR MAN": "motorman",
    "MOTORMAN": "motorman", "MTM": "motorman", "MSM": "messman",
    "CADET": "deck_cadet", "ETO": "eto", "ELECTRO TECHNICAL OFFICER": "eto",
    "FITTER ENGINE": "fitter", "GAS FITTER": "gas_fitter",
    "JR 3RD OFF": "junior_third_officer", "JR 4 ENG": "junior_fourth_engineer",
}


def normalize_rank(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = " ".join(str(value).strip().replace("_", " ").split())
    if not cleaned:
        return None
    alias = RANK_ALIASES.get(cleaned.upper())
    return alias or cleaned.lower().replace(" ", "_")
