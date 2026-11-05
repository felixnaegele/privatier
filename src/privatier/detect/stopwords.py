"""Words the AI layer must never replace.

The local AI sometimes mistakes common research or clinical words for names or
organisations, especially single words without context ("Intervention" as an
organisation, "Patient" as a person). Replacing them would damage the data for
analysis (group labels, column names) without protecting anyone.

This list only filters AI findings. Rule-based findings and column headers
are unaffected. Matching ignores upper/lower case. Add words as needed.
"""

import re

STOPWORDS = {
    # pronouns (capitalised at the start of a sentence)
    "wir",
    # people / roles
    "patient", "patientin", "patienten", "patientinnen", "pat.", "proband", "probandin", "probanden",
    "teilnehmer", "teilnehmerin", "teilnehmende", "participant", "participants", "subject", "subjects",
    "arzt", "ärztin", "ärzte", "hausarzt", "hausärztin", "doctor", "physician", "nurse", "pflege",
    "herr", "frau", "mr", "mrs", "ms", "dr", "dr.", "prof", "prof.", "pat", "kollege", "kollegin",
    # relatives: the word itself is not a name
    "vater", "mutter", "sohn", "tochter", "bruder", "schwester", "ehefrau", "ehemann", "mann", "enkel", "enkelin",
    "familie", "betreuer", "betreuerin", "angehörige", "angehöriger",
    # kinds of documents, often part of a file name
    "gutachten", "protokoll", "verlauf", "einwilligung", "interview", "brief", "entlassung", "entlassungsbericht",
    "anamnese", "aufnahme", "akte", "unterlagen", "scan", "kopie", "entwurf", "version", "teilnehmer",
    # abbreviations and diseases named after people
    "rs", "icd", "copd", "nyha", "gold", "morbus", "parkinson", "alzheimer", "crohn", "basedow", "hashimoto",
    "barthel", "glasgow", "cushing", "hodgkin", "wegener", "bechterew", "raynaud", "sjögren", "addison",
    # study design
    "intervention", "interventionsgruppe", "kontrolle", "kontrollgruppe", "control", "controls",
    "control group", "placebo", "verum", "gruppe", "group", "arm", "studie", "study", "trial",
    "baseline", "follow-up", "visite", "visit", "screening", "randomisierung", "randomization",
    "kohorte", "cohort", "fall", "case", "cases", "fälle",
    # common variables / headers
    "geschlecht", "sex", "gender", "männlich", "weiblich", "divers", "male", "female", "alter", "age",
    "diagnose", "diagnosis", "therapie", "therapy", "behandlung", "treatment", "outcome", "score",
    "name", "vorname", "nachname", "datum", "date", "telefon", "phone", "email", "e-mail", "adresse",
    "address", "kontakt", "contact", "bemerkung", "bemerkungen", "notes", "note", "id", "mrn",
    # clinical settings and documents (generic words, not specific institutions)
    "klinik", "clinic", "hospital", "krankenhaus", "station", "ambulanz", "praxis", "labor",
    "laboratory", "notaufnahme", "emergency department", "intensivstation", "icu",
    "arztbrief", "befund", "bericht", "report", "discharge summary", "entlassbrief", "epikrise",
}


# An AI finding starting with one of these describes a condition or a group, not a person or an organisation.
_NEVER_FIRST = {"morbus", "gruppe", "group", "typ", "stadium", "syndrom"}

_MONTHS = {"januar", "februar", "märz", "april", "mai", "juni", "juli", "august", "september", "oktober",
           "november", "dezember", "frühling", "sommer", "herbst", "winter"}
_NAMED_AFTER = re.compile(
    r"^-(?:krankheit|syndrom|zeichen|reflex|test|score|index|skala|klassifikation|operation|technik|methode)\b",
    re.IGNORECASE,
)
_BEFORE_MONTH = {"im", "in", "am", "bis", "seit", "vom", "zum", "ab", "anfang", "mitte", "ende", "jeden", "letzten",
                 "nächsten", "naechsten", "diesen"}
_AFTER_LANGE = {"zeit", "jahre", "monate", "wochen", "tage", "stunden", "nicht", "her"}


def is_stopword(text: str) -> bool:
    cleaned = " ".join(text.split()).casefold().strip(" .,:;")
    return cleaned in STOPWORDS or cleaned.split(" ")[0] in _NEVER_FIRST


def is_ordinary_use(text: str, before: str, after: str) -> bool:
    """"im Mai" or "Lange Zeit": a word that is also a surname, here clearly used as an ordinary word.

    Only clear cases count. In any doubt the word stays a name, as leaving a real name behind is worse.
    """
    if _NAMED_AFTER.match(after):
        return True  # "Berger-Krankheit" is a disease, whoever else is called Berger
    word = text.casefold()
    previous = before.split()[-1].casefold() if before.split() else ""
    following = after.split()[0].casefold().strip(".,;:") if after.split() else ""
    if word in _MONTHS:
        return previous in _BEFORE_MONTH or previous.rstrip(".").isdigit() or following.isdigit()
    return word == "lange" and following in _AFTER_LANGE
