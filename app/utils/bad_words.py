BAD_WORDS = {
    "fuck", "fucking", "fucked", "fucker", "fuckers", "fuck you", "fck",
    "shit", "shitting", "shitted", "shite",
    "ass", "asses", "asshole", "assholes", "arse", "arsehole",
    "bitch", "bitches", "bitching", "son of a bitch",
    "bastard", "bastards",
    "damn", "dammit",
    "cock", "cocks", "cocksucker", "dick", "dicks", "dickhead",
    "piss", "pissing", "pissed",
    "cunt", "cunts",
    "whore", "whores",
    "slut", "sluts",
    "motherfucker", "motherfucking", "mf",
    "nigger", "nigga", "niggas",
    "fag", "faggot", "faggots",
    "retard", "retarded",
    "bollocks",
    "twat",
    "wanker",
}


def contains_bad_words(text: str) -> bool:
    lower = text.lower()
    words = lower.split()
    for word in words:
        stripped = word.strip(".,!?;:'\"()[]{}<>@#$%^&*-_+=~`|/\\")
        if stripped in BAD_WORDS:
            return True
    return False
