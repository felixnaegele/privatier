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
    # English: relatives, roles, documents
    "father", "mother", "son", "daughter", "brother", "sister", "wife", "husband", "partner", "family", "guardian",
    "caregiver", "interpreter", "consultant", "surgeon", "letter", "summary", "note", "discharge", "admission",
    "patient's", "doctor's",
    # statistics and scores named after people
    "kaplan-meier", "kaplan", "meier", "cox", "fisher", "wilcoxon", "mann-whitney", "whitney", "pearson", "spearman",
    "bonferroni", "student", "bland-altman", "kruskal-wallis", "shapiro-wilk", "carpentier", "alfieri", "edwards",
    "medtronic", "abbott", "st. jude", "st jude", "euroscore", "nyha", "apgar", "syntax", "goldman", "framingham",
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
_NEVER_FIRST = {
    "morbus", "gruppe", "group", "typ", "type", "stadium", "stage", "syndrom", "syndrome", "kaplan-meier", "mann-whitney",
    "bland-altman", "kruskal-wallis", "shapiro-wilk", "carpentier", "carpentier-edwards", "alfieri", "cox", "wilcoxon",
    "fisher", "pearson", "spearman", "bonferroni", "euroscore", "nyha", "st.", "st", "cohort", "kohorte", "control", "arm",
}

_MONTHS = {"januar", "februar", "märz", "april", "mai", "juni", "juli", "august", "september", "oktober",
           "november", "dezember", "frühling", "sommer", "herbst", "winter",
           "may", "january", "february", "march", "june", "july", "october", "december", "spring", "summer", "autumn", "fall"}
_NAMED_AFTER = re.compile(
    r"^(?:-(?:krankheit|syndrom|zeichen|reflex|test|score|index|skala|klassifikation|operation|technik|methode)\b"
    r"|(?:'s|s'|')?\s+(?:disease|syndrome|sign|reflex|test|score|index|scale|classification|operation|procedure|"
    r"technique|method|regression|ring|valve|repair|stitch|krankheit|syndrom|klassifikation)\b)",
    re.IGNORECASE,
)
_BEFORE_MONTH = {"im", "in", "am", "bis", "seit", "vom", "zum", "ab", "anfang", "mitte", "ende", "jeden", "letzten",
                 "nächsten", "naechsten", "diesen", "since", "until", "from", "by", "last", "next", "this", "of", "early",
                 "late", "during", "before", "after"}
# "Lange Zeit", "White blood cells": an ordinary word, whoever else is called that.
_ORDINARY_PHRASES = {
    "lange": {"zeit", "jahre", "monate", "wochen", "tage", "stunden", "nicht", "her"},
    "long": {"term", "qt", "covid", "stay", "time", "bone", "standing", "acting"},
    "white": {"blood", "cell", "cells", "matter", "coat", "count"},
    "black": {"stool", "stools", "box", "out"},
    "brown": {"fat", "adipose"},
    "young": {"adult", "adults", "patient", "patients", "age", "people"},
    "may": {"be", "have", "need", "require", "also", "not", "cause", "help", "occur"},
    "will": {"be", "have", "need", "require", "also", "not", "continue", "return", "follow"},
    "mark": {"improvement", "ed"},
    "hope": {"to", "that"},
    "green": {"tea", "sputum"},
    "little": {"evidence", "change", "or"},
}


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
    if following in _ORDINARY_PHRASES.get(word, ()):
        return True
    return word in _MONTHS and (previous in _BEFORE_MONTH or previous.rstrip(".").isdigit() or following.isdigit())
