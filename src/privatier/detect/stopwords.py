"""Words the AI layer must never replace.

The local AI sometimes mistakes common research or clinical words for names or
organisations, especially single words without context ("Intervention" as an
organisation, "Patient" as a person). Replacing them would damage the data for
analysis (group labels, column names) without protecting anyone.

This list only filters AI findings. Rule-based findings and column headers
are unaffected. Matching ignores upper/lower case. Add words as needed.
"""

STOPWORDS = {
    # pronouns (capitalised at the start of a sentence)
    "wir",
    # people / roles
    "patient", "patientin", "patienten", "patientinnen", "pat.", "proband", "probandin", "probanden",
    "teilnehmer", "teilnehmerin", "teilnehmende", "participant", "participants", "subject", "subjects",
    "arzt", "ärztin", "ärzte", "hausarzt", "hausärztin", "doctor", "physician", "nurse", "pflege",
    "herr", "frau", "mr", "mrs", "ms", "dr", "dr.", "prof", "prof.",
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


def is_stopword(text: str) -> bool:
    return " ".join(text.split()).casefold().strip(" .,:;") in STOPWORDS
