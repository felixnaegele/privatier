import pytest

from privatier.detect import PatternDetector, resolve_overlaps
from privatier.tables import classify_header

D = PatternDetector()


def found(text):
    return {(s.entity_type, s.text) for s in resolve_overlaps(D.detect(text))}


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Mail an max.mueller@example.de bitte", ("EMAIL", "max.mueller@example.de")),
        ("Tel. 030 1234567", ("PHONE", "030 1234567")),
        ("call +49 89 98765432 now", ("PHONE", "+49 89 98765432")),
        ("phone (617) 555-0199", ("PHONE", "(617) 555-0199")),
        ("geb. 12.05.1975 in", ("DATE", "12.05.1975")),
        ("born 1975-05-12.", ("DATE", "1975-05-12")),
        ("am 14. März 2023 verschoben", ("DATE", "14. März 2023")),
        ("on March 3rd, 2021 she", ("DATE", "March 3rd, 2021")),
        ("IBAN DE89 3704 0044 0532 0130 00", ("IBAN", "DE89 3704 0044 0532 0130 00")),
        ("KVNR A123456789", ("ID", "A123456789")),
        ("Fallnummer: 998877", ("ID", "998877")),
        ("MRN 12345678", ("ID", "12345678")),
        ("wohnhaft Lindenstraße 12, 10115 Berlin.", ("ADDRESS", "Lindenstraße 12, 10115 Berlin")),
        ("Lives at 742 Evergreen Terrace", ("ADDRESS", "742 Evergreen Terrace")),
        ("Frau Dr. Lena Hoffmann rief an", ("PERSON", "Lena Hoffmann")),
        ("Herrn Klaus-Peter Becker", ("PERSON", "Klaus-Peter Becker")),
        ("Mr. Brian O'Neill called", ("PERSON", "Brian O'Neill")),
        ("Name: Müller, Max", ("PERSON", "Müller, Max")),
        ("Patientin Anna Schmidt kam", ("PERSON", "Anna Schmidt")),
    ],
)
def test_detects(text, expected):
    assert expected in found(text)


@pytest.mark.parametrize(
    "text",
    [
        "HbA1c 6.8 % nach 12 Wochen, p = 0.03",
        "Version 1.2.3 of the software",
        "n = 245 patients, mean age 63.4 years",
        "Patient Data was analysed",
        "Die Dosis wurde auf 10 mg erhöht.",
    ],
)
def test_no_false_alarms(text):
    assert found(text) == set()


@pytest.mark.parametrize(
    "header, category",
    [
        ("Vorname", "PERSON"),
        ("Nachname", "PERSON"),
        ("Last name", "PERSON"),
        ("Geburtsdatum", "DOB"),
        ("Date of birth", "DOB"),
        ("Patienten-ID", "ID"),
        ("Patientennummer", "ID"),
        ("MRN", "ID"),
        ("E-Mail", "EMAIL"),
        ("Telefon", "PHONE"),
        ("Straße", "ADDRESS"),
        ("PLZ", "ADDRESS"),
        ("HbA1c", None),
        ("Gruppe", None),
        ("Outcome", None),
        ("Patient notes", None),
    ],
)
def test_header_classification(header, category):
    assert classify_header(header) == category


def test_name_ends_at_the_end_of_a_short_line():
    spans = PatternDetector().detect("Betreff: Herr Max Müller\nGeburtsdatum: 03.11.1962\nAlles gut.")
    assert [s.text for s in spans if s.entity_type == "PERSON"] == ["Max Müller"]


def test_name_continues_after_a_long_wrapped_line():
    text = "Wir berichten hier ausführlich über den Verlauf bei Herrn Max\nMüller aus der Ambulanz."
    spans = PatternDetector().detect(text)
    assert [" ".join(s.text.split()) for s in spans if s.entity_type == "PERSON"] == ["Max Müller"]


def test_label_on_the_next_line_is_never_part_of_a_name():
    text = "Wir berichten hier ausführlich über den Verlauf bei Herrn Max Müller\nDiagnose: gut"
    spans = PatternDetector().detect(text)
    assert [s.text for s in spans if s.entity_type == "PERSON"] == ["Max Müller"]
