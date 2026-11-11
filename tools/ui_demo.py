"""Open the app's screen in a normal browser, with made-up data. For working on the design only.

Writes a copy of src/privatier/app/ui.html as index.html, with a stand-in for the Python side that answers every
call with mock data (German and English names, nothing real). The shipped ui.html is not changed.

    python tools/ui_demo.py                 # writes to a folder under $TMPDIR and prints the path
    python tools/ui_demo.py some_folder     # writes some_folder/index.html
    python tools/ui_demo.py --open          # also opens it in the default browser

Add to the address to jump to a screen or change the mock:

    ?state=review | answered | open | sheet | busy | done | restore | restored | noai | error
                            (answered: all questions answered; open: all sections open; sheet: the password sheet)
    ?theme=dark | light     force a colour scheme, whatever the system uses
    ?n=5000                 number of findings (default 300)
    ?delay=0.2              make the waiting times shorter or longer (default 1)
    ?single=1  ?haskey=1  ?uncheckable=1
    Password "wrongpass" shows the wrong-password message, an added word containing "fail" shows an error,
    one containing "none" is not found in the files, one containing "done" was already replaced.
"""

from __future__ import annotations

import os
import re
import sys
import tempfile
import webbrowser
from pathlib import Path

PAGE = Path(__file__).resolve().parent.parent / "src" / "privatier" / "app" / "ui.html"

MOCK = r"""
<script>
/* Demo only: a stand-in for the Python side. Injected by tools/ui_demo.py, never shipped. */
(function () {
  "use strict";
  const query = new URLSearchParams(location.search);
  const want = query.get("state") || "start";
  const speed = Number(query.get("delay") || 1);
  const howMany = Number(query.get("n") || 300);
  if (query.get("theme")) document.documentElement.dataset.theme = query.get("theme");
  const wait = ms => new Promise(done => setTimeout(done, ms * speed));
  let seed = 7;
  const rnd = () => { seed = (seed * 16807) % 2147483647; return (seed - 1) / 2147483646; };
  const pick = list => list[Math.floor(rnd() * list.length)];
  const base = path => String(path).replace(/\/+$/, "").split("/").pop();

  const FIRST = ["Max", "Anna", "Jürgen", "Sabine", "Björn", "Käthe", "Wolfgang", "Ayşe", "Mehmet", "Lena", "Heinz-Peter", "Ursula",
    "James", "Mary", "Oliver", "Emily", "Siobhán", "Liam", "Grace", "Thomas", "Charlotte", "Mohammed", "Priya", "Wei"];
  const LAST = ["Müller", "Schmidt", "Schneider", "Weiß", "Großmann", "Öztürk", "von der Heide", "Meyer-Lindenberg", "Köhler", "Jäger",
    "Yılmaz", "Nowak", "Smith", "Johnson", "O'Connor", "Williams", "Taylor", "Brown", "Patel", "Nguyen", "MacDonald", "Evans"];
  const STREET = ["Hauptstraße", "Bahnhofstraße", "Am Mühlenberg", "Lindenallee", "Schillerplatz", "High Street", "Church Lane", "Victoria Road", "Mill Lane"];
  const PLACE = ["Freiburg im Breisgau", "München", "Köln", "Bad Krozingen", "Tübingen", "Zürich", "London", "Manchester", "Edinburgh", "Boston", "Leeds", "Wien"];
  const ORG = ["Universitätsklinikum Freiburg", "Herzzentrum Bad Krozingen", "Charité Berlin", "St. Josefskrankenhaus", "Praxis Dr. Köhler",
    "Royal Infirmary of Edinburgh", "Massachusetts General Hospital", "St Thomas' Hospital", "AOK Baden-Württemberg", "Guy's and St Thomas' NHS Foundation Trust"];
  const FILES = ["Patienten.xlsx", "Follow-up.sav", "outcomes.csv", "Arztbrief_Mueller.docx", "discharge_letter_03.pdf", "notes.txt", "Auswertung.R", "OP-Berichte.docx"];
  const TYPES = [
    ["name", "Name", 34], ["BIRTH_DATE", "Date of birth", 12], ["date", "Date", 14], ["id", "Patient ID", 14], ["phone", "Phone number", 5],
    ["email", "Email address", 4], ["address", "Address", 6], ["place", "Place", 6], ["org", "Organisation", 5],
  ];
  const two = n => String(n).padStart(2, "0");
  function value(type, i) {
    const first = pick(FIRST), last = pick(LAST), year = 1930 + Math.floor(rnd() * 70), day = 1 + Math.floor(rnd() * 28), month = 1 + Math.floor(rnd() * 12);
    if (type === "name") return [`${first} ${last}`, `${last}, ${first}`, `Dr. ${last}`, `Frau ${last}`, `Mr ${last}`, last][i % 6];
    if (type === "BIRTH_DATE") return `${year}-${two(month)}-${two(day)}`;
    if (type === "date") return i % 2 ? `${two(day)}.${two(month)}.${2015 + i % 9}` : `${two(month)}/${two(day)}/${2015 + i % 9}`;
    if (type === "id") return [`P-${10000 + i * 37}`, `Fallnummer ${700000 + i * 113}`, `MRN ${4400000 + i * 71}`][i % 3];
    if (type === "phone") return i % 2 ? `0761 ${100000 + i * 977}` : `+44 20 7946 ${two(i % 100)}${two((i * 7) % 100)}`;
    if (type === "email") return `${first}.${last}`.toLowerCase().replace(/[^a-z.]/g, "") + (i % 2 ? "@uniklinik-freiburg.example" : "@nhs.example");
    if (type === "address") return `${pick(STREET)} ${1 + i % 140}, ${10000 + i * 613 % 89999} ${pick(PLACE)}`;
    if (type === "place") return PLACE[i % PLACE.length] + (i >= PLACE.length ? ` ${Math.floor(i / PLACE.length) + 1}` : "");
    return ORG[i % ORG.length] + (i >= ORG.length ? ` (Station ${i})` : "");
  }
  function makeFindings(total) {
    const weight = TYPES.reduce((sum, t) => sum + t[2], 0);
    const out = [], seen = new Set();
    for (const [type, label, share] of TYPES) {
      const n = Math.max(1, Math.round(total * share / weight));
      for (let i = 0; i < n; i++) {
        let text = value(type, i);
        while (seen.has(type + text)) text += " " + (i + 2);
        seen.add(type + text);
        const files = FILES.filter(() => rnd() < 0.3);
        if (!files.length) files.push(pick(FILES));
        const column = ["name", "BIRTH_DATE", "id"].includes(type) && i % 3 === 0;
        out.push({
          id: `${type}:${i}`, type, label, value: text, count: 1 + Math.floor(rnd() * rnd() * 60), files,
          source: column ? "column" : type === "name" || type === "place" || type === "org" ? pick(["ai", "rule", "known"]) : pick(["rule", "known"]),
          can_keep: !column, kept: false, already_replaced: 0,
        });
      }
    }
    out.push({ id: "name:long", type: "name", label: "Name", value: "Prof. Dr. med. Dr. h.c. Karl-Friedrich Maximilian Freiherr von und zu Hohenstein-Wartenberg", count: 2, files: ["Arztbrief_Mueller.docx"], source: "ai", can_keep: true, kept: false, already_replaced: 0 });
    out.push({ id: "insurance:0", type: "insurance", label: "Insurance number", value: "A123456780", count: 1, files: ["Patienten.xlsx"], source: "rule", can_keep: true, kept: false, already_replaced: 0 });
    return out;
  }

  const LEVELS = [
    { number: 1, name: "Pseudonymised", keeps_key: true, summary: "Names and IDs become codes. Everything else stays exactly as it is, and you can put the real values back with your key." },
    { number: 2, name: "Less detail", keeps_key: true, summary: "As level 1, and dates keep only month and year. Age stays exact. You can still put the real values back." },
    { number: 3, name: "Strongly reduced", keeps_key: false, summary: "Random codes and no key. Dates become the year, age becomes 10-year bands, free text is emptied and letters are left out." },
    { number: 4, name: "Anonymisation attempt", keeps_key: false, summary: "As level 3, with dates removed and details blanked for patients who would still stand out. The result is then checked." },
  ];
  const COLUMNS = ["Diagnose", "Hauptdiagnose (ICD)", "Klappentyp", "Bemerkung", "Komplikationen", "Medication", "Comment", "NYHA", "LVEF", "Smoking status",
    "Rare disease", "Operateur-Kommentar", "Entlassart", "BMI", "Creatinine"].map((header, i) => ({
      ref: [i % 2 ? "Follow-up.sav" : "Patienten.xlsx", i % 2 ? "" : "Stammdaten", i + 3], table: i % 2 ? "Follow-up.sav" : "Patienten.xlsx: Stammdaten", header,
    }));
  const QUESTIONS = [
    { id: "same|mueller", kind: "same_name", letters_only: false, files: ["Patienten.xlsx", "Follow-up.sav", "Arztbrief_Mueller.docx", "notes.txt"],
      text: "Max Müller appears with no birth date or ID in 4 files. Is this the same person as Max Müller (born 12.05.1961; ID P-10037)?",
      options: [{ value: "same", label: "Yes, the same person" }, { value: "different", label: "No, someone else" }, { value: "unsure", label: "I do not know" }] },
    { id: "column|Patienten.xlsx|Stammdaten|7", kind: "column", letters_only: false, files: ["Patienten.xlsx"],
      text: "Patienten.xlsx, Stammdaten, column H has no header, and its values look like dates. What is it?",
      options: [{ value: "birth", label: "Birth dates" }, { value: "date", label: "Other dates" }, { value: "keep", label: "Nothing personal, keep it" }] },
    { id: "mention|smith", kind: "mention", letters_only: true, files: ["discharge_letter_03.pdf"],
      text: "\"Mr Smith\" appears in discharge_letter_03.pdf with only a surname. Is this the patient James Smith (born 1954)?",
      options: [{ value: "yes", label: "Yes" }, { value: "no", label: "No, another person" }] },
  ];
  const TABLES = [
    { title: "Patienten.xlsx: Stammdaten", unit: "patients", total: 412, characteristics: ["sex", "age", "OP-Datum", "Entlassdatum"] },
    { title: "Follow-up.sav", unit: "patients", total: 398, characteristics: ["sex", "age", "date_followup"] },
    { title: "outcomes.csv", unit: "rows", total: 1260, characteristics: ["sex", "death_date"] },
    { title: "Linked by patient code", unit: "patients", total: 412, characteristics: ["sex", "age", "OP-Datum", "Entlassdatum", "date_followup", "death_date"] },
  ];
  const SHARE = { 1: [86.4, 71.1, 12.5, 97.3], 2: [61.2, 40.5, 6.1, 78.4], 3: [7.3, 3.5, 0.4, 9.2], 4: [0, 0, 0, 0] };
  const session = { findings: [], extra: [], keep: [], single: false, job: "", step: 0 };

  function preview(answers, ticked, keptText) {
    answers = answers || {}; ticked = ticked || []; keptText = keptText || [];
    const out = {};
    for (const level of LEVELS) {
      const n = level.number;
      const tables = TABLES.map((t, i) => {
        const percent = Math.min(100, SHARE[n][i] + (n < 4 ? ticked.length * 2.5 : 0));
        const singled = Math.round(t.total * percent / 100);
        const small = Math.min(t.total, Math.round(singled * 1.2));
        return { ...t, status: "checked", reason: "", singled_out: singled, percent: Math.round(percent * 10) / 10, in_small_group: small,
          percent_small: Math.round(small / t.total * 1000) / 10, characteristics: [...t.characteristics, ...ticked.map(r => COLUMNS.find(c => c.ref[2] === r[2]).header)],
          blanked_rows: 0, not_compared: 14 };
      });
      const broken = query.get("uncheckable")
        ? [{ title: "Labor.xlsx: Werte", status: "could_not_check", reason: "the header row was not found", unit: "rows", total: 0, singled_out: 0, percent: 0, in_small_group: 0, percent_small: 0, characteristics: [], blanked_rows: 0, not_compared: 0 }]
        : [];
      const lost = [];
      const date = (header, table, change) => lost.push({ ref: [table, "", lost.length], table, header, change, free_text: false });
      if (answers["column|Patienten.xlsx|Stammdaten|7"] === "birth") date("(column H)", "Patienten.xlsx: Stammdaten", n < 3 ? "year only" : "decade of birth only");
      if (n === 2) { date("OP-Datum", "Patienten.xlsx: Stammdaten", "day removed (month and year stay)"); date("Entlassdatum", "Patienten.xlsx: Stammdaten", "day removed (month and year stay)"); date("date_followup", "Follow-up.sav", "day removed (month and year stay)"); date("death_date", "outcomes.csv", "year only"); }
      if (n >= 3) {
        const change = n === 3 ? "year only" : "removed";
        date("OP-Datum", "Patienten.xlsx: Stammdaten", change); date("Entlassdatum", "Patienten.xlsx: Stammdaten", change); date("date_followup", "Follow-up.sav", change); date("death_date", "outcomes.csv", change);
        date("Alter", "Patienten.xlsx: Stammdaten", "10-year bands"); date("Geburtsdatum", "Patienten.xlsx: Stammdaten", "decade of birth only");
        for (const c of COLUMNS.filter(c => ["Bemerkung", "Comment", "Operateur-Kommentar"].includes(c.header))) {
          const kept = keptText.some(r => r[0] === c.ref[0] && r[2] === c.ref[2]);
          lost.push({ ref: c.ref, table: c.table, header: c.header, change: kept ? "kept on your request" : "free text emptied", free_text: true, kept });
        }
      }
      const reasons = [];
      let label, anonymous = false;
      if (level.keeps_key) { label = `${level.name}: still personal data`; reasons.push("A key exists, so patients can be identified again."); }
      else {
        if (n !== 4) reasons.push("Only level 4 can count as anonymous.");
        for (const b of broken) reasons.push(`Could not check ${b.title} (${b.reason}).`);
        for (const t of tables) if (t.in_small_group) reasons.push(`${t.title}: ${t.in_small_group} of ${t.total} ${t.unit} share their characteristics with fewer than 4 others.`);
        if (keptText.length) reasons.push(`Patienten.xlsx: Stammdaten: free text remains in ${keptText.map(r => COLUMNS.find(c => c.ref[2] === r[2]).header).join(", ")}.`);
        if (reasons.length) label = "Reduced detail, not anonymous";
        else {
          anonymous = true; label = "Anonymous by this check";
          reasons.push("Every patient shares sex, age and every date column with at least 4 others, in every table.",
            `Other columns were not compared unless you ticked them (${42 - ticked.length} here, such as clinical values). Someone who knows a rare value could still recognise a patient.`,
            "Row order is unchanged: a table sorted by date or name can give hints.",
            "Whether this counts as anonymous in law is for your data protection officer to decide.");
        }
      }
      const checked = tables.slice().sort((a, b) => b.percent - a.percent);
      out[String(n)] = { worst: checked[0], tables: [...tables, ...broken], could_not_check: broken, lost,
        left_out: n >= 3 ? ["Arztbrief_Mueller.docx", "discharge_letter_03.pdf", "notes.txt", "OP-Berichte.docx", "Auswertung.R"] : [],
        blanked_rows: n === 4 ? 23 : 0, label, anonymous, reasons, min_group: 5 };
    }
    return out;
  }

  function scanResult(paths) {
    // A word with "none" in it is not found, one with "done" was already replaced.
    const added = session.extra.map((term, i) => {
      const count = /none|done/i.test(term) ? 0 : 3 + i * 4;
      return { id: `TERM:${term}`, type: "TERM", label: "Word added by you", value: term, count, already_replaced: /done/i.test(term) ? 5 : 0,
        files: count ? FILES.slice(0, 1 + i % 4) : [], source: "added", can_keep: false, kept: false };
    });
    const keep = new Set(session.keep);
    return {
      folder: session.name, path: session.path, single: session.single, used_ai: session.usedAi, tables: 3, other_files: 5,
      unsupported: ["scan_0001.jpg", "alte_Liste.xls"], named_files: 1, questions: QUESTIONS,
      notes: ["Arztbrief_Mueller.docx: the file name contains a name from the data. File names are never changed, so look before you upload.",
        "Patienten.xlsx: 2 formulas use an identifying column, so their stored results are removed.",
        "discharge_letter_03.pdf becomes a text file, discharge_letter_03.pdf.md."],
      columns: COLUMNS, has_key: Boolean(query.get("haskey")), levels: LEVELS, preview: preview({}, [], []),
      findings: [...session.findings.map(f => ({ ...f, kept: keep.has(f.id) })), ...added],
    };
  }

  const STATUS = { scan: ["Loading the local AI model", "Reading your files · File 1 of 8", "Reading your files · File 3 of 8", "Reading your files · File 6 of 8", "Reading your files · File 8 of 8", "Working out who is who"],
    export: ["Writing the copy and checking it", "Writing the copy · File 2 of 8", "Writing the copy · File 7 of 8", "Checking the files as written"],
    restore: ["Opening the key", "Putting the real values back"] };

  window.pywebview = { api: {
    async startup() { await wait(150); return { ai_ready: want !== "noai", version: "0.1 demo" }; },
    async choose(kind) {
      await wait(300);
      if (kind === "key") return ["/Users/demo/Documents/Studie_privatier/key.vault"];
      if (kind === "files") return ["/Users/demo/Documents/Studie/Patienten.xlsx", "/Users/demo/Documents/Studie/Follow-up.sav"];
      return ["/Users/demo/Documents/Studie"];
    },
    async status() { if (!session.job) return ""; const list = STATUS[session.job]; session.step += 1; return list[Math.min(list.length - 1, Math.floor(session.step / 2))]; },
    async scan(paths, useAi) {
      session.job = "scan"; session.step = 0;
      await wait(want === "busy" ? 600000 : 4200);
      session.job = "";
      if (want === "error") return { error: "Nothing in this folder could be read. Privatier reads Excel, SPSS, CSV, Word, PDF and text files." };
      session.path = paths[0]; session.single = Boolean(query.get("single")) || (paths.length === 1 && /\.\w+$/.test(paths[0]));
      session.name = paths.length > 1 ? `${paths.length} files` : base(paths[0]);
      session.usedAi = Boolean(useAi) && want !== "noai"; session.extra = []; session.keep = []; seed = 7; session.findings = makeFindings(howMany);
      return scanResult();
    },
    async review(keep, extra) {
      await wait(1600);
      if (extra.some(t => /fail/i.test(t))) return { error: "The files could not be read again. Nothing was changed." };
      session.extra = extra.slice(); session.keep = keep.slice();
      return scanResult();
    },
    async preview(answers, ticked, keptText) { await wait(350); return preview(answers, ticked, keptText); },
    async export(level, password, answers, ticked, keptText, keep, extra) {
      session.job = "export"; session.step = 0;
      await wait(3200);
      session.job = "";
      if (password === "wrongpass") return { error: "This is not the password of the existing key for this folder." };
      const p = preview(answers, ticked, keptText)[String(level)];
      const names = { 1: "_pseudonymised", 2: "_less_detail", 3: "_strongly_reduced", 4: "_level4" };
      const root = session.path.replace(/\.\w+$/, "");
      return { worst: p.worst, tables: p.tables, could_not_check: p.could_not_check, output: root + names[level], label: p.label, anonymous: p.anonymous,
        reasons: p.reasons, processed: 8, kept: (keep || []).length,
        skipped: [{ file: "scan_0001.jpg", reason: "images are not supported yet" }, { file: "alte_Liste.xls", reason: "old Excel files are not supported yet" },
          ...p.left_out.map(f => ({ file: f, reason: "letters are left out at this level" }))],
        errors: level === 2 ? [{ file: "Labor_defekt.xlsx", reason: "this file could not be processed, so it is not in the copy" }] : [],
        notes: ["Patienten.xlsx: 2 stored formula results were removed, as they could reveal the data.", "privacy_report.txt lists what was changed, with counts and column names only."],
        report: root + "_privatier/privacy_report.txt", key_dir: LEVELS[level - 1].keeps_key ? root + "_privatier" : null };
    },
    async restore_info(paths) {
      await wait(500);
      if (paths.some(p => /empty/i.test(p))) return { error: "There is nothing in this folder that Privatier can read." };
      return { name: paths.length > 1 ? `${paths.length} files` : base(paths[0]), files: paths.length > 1 ? paths.length : 6,
        suggested_key: paths.some(p => /nokey/i.test(p)) ? null : "/Users/demo/Documents/Studie_privatier/key.vault" };
    },
    async restore(paths, keyPath, password) {
      session.job = "restore"; session.step = 0;
      await wait(2600);
      session.job = "";
      if (password === "wrongpass") return { error: "This is not the password of this key file." };
      return { output: paths[0].replace(/\.\w+$/, "") + "_restored", restored: 5, values: 1284, unknown: 2,
        skipped: [{ file: "figure_1.png", reason: "images are not supported yet" }], errors: [] };
    },
    async show_in_finder(path) { console.log("show in Finder:", path); },
  } };

  // A real drop in the browser has no full paths: make some up.
  document.addEventListener("drop", e => {
    const names = [...(e.dataTransfer ? e.dataTransfer.files : [])].map(f => "/Users/demo/Desktop/" + f.name);
    if (names.length) window.itemsDropped(names);
  });

  const shown = id => new Promise(done => { const t = setInterval(() => { if (!document.getElementById(id).classList.contains("hidden")) { clearInterval(t); done(); } }, 50); });
  window.addEventListener("load", async () => {
    window.dispatchEvent(new Event("pywebviewready"));
    await wait(300);
    const click = id => document.getElementById(id).click();
    const type = (id, value) => { const el = document.getElementById(id); el.value = value; el.dispatchEvent(new Event("input", { bubbles: true })); };
    if (["review", "answered", "open", "sheet", "busy", "done", "error", "noai"].includes(want)) window.itemsDropped(["/Users/demo/Documents/Studie"]);
    if (["answered", "open", "sheet", "done"].includes(want)) await shown("review");
    if (want === "answered" || want === "open") for (let i = 0; i < 3; i++) document.querySelector("#question-options button").click();
    if (want === "open") { ["head-level", "head-found", "head-lost"].forEach(click); document.querySelector(".group-head").click(); }
    if (want === "sheet" || want === "done") click("export");
    if (want === "done") { type("password", "demo-password"); type("password2", "demo-password"); click("sheet-go"); }
    if (want === "restore" || want === "restored") {
      document.querySelector('#tabs [data-value="restore"]').click();
      window.itemsDropped(["/Users/demo/Documents/Ergebnisse"]);
    }
    if (want === "restored") {
      await shown("restore-chosen");
      type("restore-password", "demo-password");
      click("restore-go");
    }
  });
})();
</script>
"""


def build(page: str) -> str:
    """The page with the mock in front of its own script, and a way to force light or dark."""
    light = re.search(r":root\s*\{([^}]*)\}", page)
    dark = re.search(r"@media \(prefers-color-scheme: dark\)\s*\{\s*:root\s*\{([^}]*)\}", page)
    if not light or not dark or page.count("<script>") != 1:
        raise SystemExit("ui.html no longer has the shape this demo expects: one <script>, and a light and a dark :root block.")
    forced = (
        "<style>\n"
        f':root[data-theme="light"] {{{light.group(1)} color-scheme: light; }}\n'
        f':root[data-theme="dark"] {{{dark.group(1)} color-scheme: dark; }}\n'
        "</style>\n"
    )
    page = page.replace("</head>", forced + "</head>", 1)
    return page.replace("<script>", MOCK + "<script>", 1)


def main(arguments: list[str]) -> None:
    folders = [a for a in arguments if not a.startswith("--")]
    folder = Path(folders[0]) if folders else Path(os.environ.get("TMPDIR") or tempfile.gettempdir()) / "privatier_ui_demo"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "index.html"
    target.write_text(build(PAGE.read_text(encoding="utf-8")), encoding="utf-8")
    print(f"Demo page written: {target}")
    print(f"Open it in a browser:  open '{target}'")
    print("Jump to a screen by adding for example ?state=review or ?state=restored&theme=dark to the address.")
    if "--open" in arguments:
        webbrowser.open(target.as_uri())


if __name__ == "__main__":
    main(sys.argv[1:])
