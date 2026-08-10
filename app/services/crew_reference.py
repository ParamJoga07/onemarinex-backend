"""Canonical crew rank and nationality values used at API boundaries.

Crew profiles have always declared nationality as ISO 3166-1 alpha-2, while
manifest rows historically stored a mix of country names, demonyms and codes.
Normalising writes prevents more mixed data without hiding legacy values that
still need an explicit repair review.
"""

from typing import Optional


# Crew manifests print the nationality column as a demonym far more often than
# as a country name ("UKRAINIAN", not "Ukraine"), so every country below lists
# its demonyms alongside its names. An entry missing its demonym is not a
# cosmetic gap: manifest import validates strictly and one unrecognised row
# rejects the whole upload.
#
# Keyed alpha-2 -> every spelling seen on a manifest. COUNTRY_ALIASES is
# inverted from this so each spelling is written exactly once.
_COUNTRY_SPELLINGS = {
    "AZ": ("AZERBAIJAN", "AZERBAIJANI", "AZERI"),
    "BD": ("BANGLADESH", "BANGLADESHI"),
    "BG": ("BULGARIA", "BULGARIAN"),
    "BR": ("BRAZIL", "BRAZILIAN"),
    "CN": ("CHINA", "CHINESE", "PEOPLES REPUBLIC OF CHINA", "PR CHINA"),
    "CO": ("COLOMBIA", "COLOMBIAN"),
    "CU": ("CUBA", "CUBAN"),
    "DE": ("GERMANY", "GERMAN"),
    "DK": ("DENMARK", "DANISH", "DANE"),
    "EE": ("ESTONIA", "ESTONIAN"),
    "EG": ("EGYPT", "EGYPTIAN"),
    "ES": ("SPAIN", "SPANISH", "SPANIARD"),
    "ET": ("ETHIOPIA", "ETHIOPIAN"),
    "FR": ("FRANCE", "FRENCH"),
    "GB": ("UK", "UNITED KINGDOM", "GREAT BRITAIN", "BRITAIN", "BRITISH",
           "ENGLAND", "ENGLISH", "SCOTLAND", "SCOTTISH", "WALES", "WELSH",
           "NORTHERN IRELAND"),
    "GE": ("GEORGIA", "GEORGIAN"),
    "GH": ("GHANA", "GHANAIAN", "GHANIAN"),
    "GR": ("GREECE", "GREEK", "HELLENIC REPUBLIC"),
    "HR": ("CROATIA", "CROATIAN", "CROAT"),
    "HU": ("HUNGARY", "HUNGARIAN"),
    "ID": ("INDONESIA", "INDONESIAN"),
    "IN": ("INDIA", "INDIAN", "REPUBLIC OF INDIA"),
    "IR": ("IRAN", "IRANIAN"),
    "IT": ("ITALY", "ITALIAN"),
    "JP": ("JAPAN", "JAPANESE"),
    "KE": ("KENYA", "KENYAN"),
    "KR": ("SOUTH KOREA", "REPUBLIC OF KOREA", "KOREA", "KOREAN",
           "SOUTH KOREAN"),
    "LK": ("SRI LANKA", "SRILANKA", "SRI LANKAN", "SRILANKAN", "CEYLON"),
    "LT": ("LITHUANIA", "LITHUANIAN"),
    "LV": ("LATVIA", "LATVIAN"),
    "MM": ("MYANMAR", "BURMA", "BURMESE", "MYANMARESE"),
    "MX": ("MEXICO", "MEXICAN"),
    "MY": ("MALAYSIA", "MALAYSIAN"),
    "NG": ("NIGERIA", "NIGERIAN"),
    "NL": ("NETHERLANDS", "DUTCH", "HOLLAND"),
    "NO": ("NORWAY", "NORWEGIAN"),
    "NP": ("NEPAL", "NEPALI", "NEPALESE"),
    "PA": ("PANAMA", "PANAMANIAN"),
    "PE": ("PERU", "PERUVIAN"),
    "PH": ("PHILIPPINES", "PHILIPPINE", "FILIPINO", "FILIPINA", "PILIPINO"),
    "PK": ("PAKISTAN", "PAKISTANI"),
    "PL": ("POLAND", "POLISH", "POLE"),
    "PT": ("PORTUGAL", "PORTUGUESE"),
    "RO": ("ROMANIA", "ROMANIAN", "RUMANIA", "ROUMANIA"),
    "RU": ("RUSSIA", "RUSSIAN", "RUSSIAN FEDERATION"),
    "SG": ("SINGAPORE", "SINGAPOREAN"),
    "TH": ("THAILAND", "THAI"),
    "TR": ("TURKEY", "TURKIYE", "TURKISH", "TURK"),
    "TZ": ("TANZANIA", "TANZANIAN"),
    "UA": ("UKRAINE", "UKRAINIAN", "UKRAINIAN FEDERATION"),
    "US": ("USA", "UNITED STATES", "UNITED STATES OF AMERICA", "AMERICAN",
           "AMERICA"),
    "VN": ("VIETNAM", "VIET NAM", "VIETNAMESE"),
    "ZA": ("SOUTH AFRICA", "SOUTH AFRICAN"),
}

COUNTRY_ALIASES = {
    spelling: code
    for code, spellings in _COUNTRY_SPELLINGS.items()
    for spelling in spellings
}


def normalize_nationality(value: Optional[str], *, strict: bool = False) -> Optional[str]:
    if value is None:
        return None
    # Manifests punctuate freely — "U.S.A.", "Sri-Lankan", "Filipino/Filipina".
    # Periods close up ("U.S.A." -> "USA"); the rest become word breaks
    # ("Sri-Lankan" -> "SRI LANKAN").
    cleaned = str(value).strip().upper().replace(".", "")
    for character in "-/\\,()":
        cleaned = cleaned.replace(character, " ")
    cleaned = " ".join(cleaned.split())
    if not cleaned:
        return None
    if len(cleaned) == 2 and cleaned.isalpha():
        return cleaned
    result = COUNTRY_ALIASES.get(cleaned)
    if result:
        return result
    if strict:
        # Naming the value it choked on turns a dead-end upload into something
        # the agent can actually correct in the manifest.
        raise ValueError(
            f"Nationality '{value}' is not a recognised country name, "
            "demonym or ISO alpha-2 code"
        )
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
