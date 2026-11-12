"""Open the app's screen in a normal browser, with made-up data. For working on the design only.

Writes a copy of src/privatier/app/ui.html as index.html, with a stand-in for the Python side that answers every
call with mock data (German and English names, nothing real). The shipped ui.html is not changed.

    python tools/ui_demo.py                 # writes to a folder under $TMPDIR and prints the path
    python tools/ui_demo.py some_folder     # writes some_folder/index.html
    python tools/ui_demo.py --open          # also opens it in the default browser

Add to the address to jump to a screen or change the mock:

    ?state=empty | project | open | protection | points | copy | result | restore | restored | nokey | busy | error | noai
                            (project: after closing the sheet that comes up; open: one file with rows opened and a value kept)
    ?theme=dark | light     force a colour scheme, whatever the system uses
    ?n=5000                 number of findings (default 300)
    ?delay=0.2              make the waiting times shorter or longer (default 1)
    ?haskey=0  ?uncheckable=1
    Password "wrongpass" shows the wrong-password message. An added word containing "fail" shows an error,
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
  const four = n => String(n).padStart(4, "0");
  const two = n => String(n).padStart(2, "0");

  const FIRST = ["Max", "Anna", "Jürgen", "Sabine", "Björn", "Käthe", "Wolfgang", "Ayşe", "Mehmet", "Lena", "Heinz-Peter", "Ursula",
    "James", "Mary", "Oliver", "Emily", "Siobhán", "Liam", "Grace", "Thomas", "Charlotte", "Mohammed", "Priya", "Wei"];
  const LAST = ["Müller", "Schmidt", "Schneider", "Weiß", "Großmann", "Öztürk", "von der Heide", "Meyer-Lindenberg", "Köhler", "Jäger",
    "Yılmaz", "Nowak", "Smith", "Johnson", "O'Connor", "Williams", "Taylor", "Brown", "Patel", "Nguyen", "MacDonald", "Evans"];
  const STREET = ["Hauptstraße", "Bahnhofstraße", "Am Mühlenberg", "Lindenallee", "Schillerplatz", "High Street", "Church Lane", "Victoria Road", "Mill Lane"];
  const PLACE = ["Freiburg im Breisgau", "München", "Köln", "Bad Krozingen", "Tübingen", "Zürich", "London", "Manchester", "Edinburgh", "Boston", "Leeds", "Wien"];
  const ORG = ["Universitätsklinikum Freiburg", "Herzzentrum Bad Krozingen", "Charité Berlin", "St. Josefskrankenhaus", "Praxis Dr. Köhler",
    "Royal Infirmary of Edinburgh", "Massachusetts General Hospital", "St Thomas' Hospital", "AOK Baden-Württemberg", "Guy's and St Thomas' NHS Foundation Trust"];
  // What the mock project holds: files, their columns in file order, and what a letter's text contains.
  const CHOICES = [{ value: "PERSON", label: "Name" }, { value: "ID", label: "ID" }, { value: "DOB", label: "Birth date" }, { value: "KEEP", label: "Not identifying" }];
  const KINDS = {
    PERSON: ["Name", "a name code", "Names"], ID: ["ID", "an ID code", "IDs"], DOB: ["Birth date", "the year", "Birth dates"], KEEP: ["Not identifying", "stays as it is", ""],
    PHONE: ["Phone number", "a phone code", "Phone numbers"], EMAIL: ["Email address", "an email code", "Email addresses"], ADDRESS: ["Address", "an address code", "Addresses"],
    LOCATION: ["Place", "a place code", "Places"], ORG: ["Organisation", "an organisation code", "Organisations"],
    INSURANCE: ["Insurance number", "an insurance code", "Insurance numbers"], TEXT: ["Free text", "names inside are replaced", ""],
  };
  // header, kind, how many different values, what the values look like when it differs from the kind
  const FILES = [
    { path: "Patienten.xlsx", kind: "table", tables: [
      { name: "Stammdaten", columns: [["Pat-ID", "ID", 40], ["Name", "PERSON", 38], ["Geburtsdatum", "DOB", 36], ["Geschlecht", "KEEP", 0], ["Alter", "KEEP", 0], ["OP-Datum", "KEEP", 0],
        ["Klappentyp", "KEEP", 0], ["", "DOB", 12], ["Bemerkung", "TEXT", 9, "PERSON"]] },
      { name: "Kontakt", columns: [["Pat-ID", "ID", 40], ["Telefon", "PHONE", 22], ["E-Mail", "EMAIL", 18], ["Straße", "ADDRESS", 30], ["Ort", "LOCATION", 12], ["Krankenkasse", "ORG", 6], ["Versichertennr.", "INSURANCE", 30]] }] },
    { path: "Follow-up.sav", kind: "table", tables: [{ name: "", columns: [["pid", "ID", 40], ["name", "PERSON", 38], ["dob", "DOB", 36], ["date_followup", "KEEP", 0], ["nyha", "KEEP", 0], ["comment", "TEXT", 6, "PERSON"]] }] },
    { path: "outcomes.csv", kind: "table", tables: [{ name: "", columns: [["patient_id", "ID", 40], ["surgeon", "PERSON", 7], ["hospital", "ORG", 4], ["death_date", "KEEP", 0], ["lvef", "KEEP", 0], ["smoking_status", "KEEP", 0]] }] },
    { path: "Briefe/Arztbrief_Mueller.docx", kind: "document", groups: [["PERSON", 9], ["DOB", 2], ["LOCATION", 4], ["ORG", 3], ["PHONE", 2]] },
    { path: "Briefe/discharge_letter_03.pdf", kind: "document", groups: [["PERSON", 6], ["DOB", 1], ["ADDRESS", 2], ["ORG", 2]] },
    { path: "Briefe/OP-Berichte_2019_bis_2023_Herzchirurgie_final_v2.docx", kind: "document",
      tables: [{ name: "", columns: [["Patient", "PERSON", 12], ["OP-Datum", "KEEP", 0], ["Operateur", "PERSON", 5]] }], groups: [["PERSON", 14], ["LOCATION", 3]] },
    { path: "notes.txt", kind: "text", groups: [["PERSON", 5], ["EMAIL", 2]] }, { path: "Auswertung.R", kind: "text", groups: [] },
    { path: "scan_0001.jpg", kind: "other", left: "images are not supported yet" }, { path: "alte_Liste.xls", kind: "other", left: "old Excel files are not supported yet" },
  ];
  const READY = FILES.filter(f => !f.left).map(f => f.path);
  const pools = {};
  function value(type, i) {
    const first = FIRST[(i * 7) % FIRST.length], last = LAST[(i * 5 + 3) % LAST.length], year = 1930 + (i * 13) % 70, day = 1 + (i * 11) % 28, month = 1 + (i * 5) % 12;
    if (type === "PERSON") return [`${first} ${last}`, `${last}, ${first}`, `Dr. ${last}`, `Frau ${last}`, `Mr ${last}`, last][i % 6] + (i >= 132 ? ` ${i}` : "");
    if (type === "DOB") return `${year}-${two(month)}-${two(day)}` + (i >= 90 ? ` (${i})` : "");
    if (type === "ID") return [`P-${10000 + i * 37}`, `Fallnummer ${700000 + i * 113}`, `MRN ${4400000 + i * 71}`][i % 3];
    if (type === "PHONE") return i % 2 ? `0761 ${100000 + i * 977}` : `+44 20 7946 ${two(i % 100)}${two((i * 7) % 100)}`;
    if (type === "EMAIL") return `${first}.${last}${i}`.toLowerCase().replace(/[^a-z0-9.]/g, "") + (i % 2 ? "@uniklinik-freiburg.example" : "@nhs.example");
    if (type === "ADDRESS") return `${STREET[i % STREET.length]} ${1 + i % 140}, ${10000 + i * 613 % 89999} ${PLACE[i % PLACE.length]}`;
    if (type === "LOCATION") return PLACE[i % PLACE.length] + (i >= PLACE.length ? ` ${Math.floor(i / PLACE.length) + 1}` : "");
    if (type === "INSURANCE") return `${"ABCDEFGHKLMN"[i % 12]}${100000000 + i * 7919}`;
    return ORG[i % ORG.length] + (i >= ORG.length ? ` (Station ${i})` : "");
  }
  function finding(type, i) {
    // One value, project-wide: the same patient ID in two tables is one finding.
    pools[type] = pools[type] || [];
    while (pools[type].length <= i) {
      const n = pools[type].length;
      const text = n === 3 && type === "PERSON" ? "Prof. Dr. med. Dr. h.c. Karl-Friedrich Maximilian Freiherr von und zu Hohenstein-Wartenberg" : n === 0 && type === "PERSON" ? "Max Müller" : n === 1 && type === "PERSON" ? "Mr Smith" : value(type, n);
      pools[type].push({ id: `${type}:${n}`, type, label: KINDS[type][0], value: text, becomes: type === "DOB" ? text.slice(0, 4) : `${type}_${four(n + 1)}`,
        source: ["PERSON", "LOCATION", "ORG"].includes(type) ? ["ai", "rule", "known", "column"][n % 4] : ["rule", "column"][n % 2], can_keep: true, kept: false, already_replaced: 0 });
    }
    return pools[type][i];
  }
  const scale = howMany / 300;
  const many = n => Math.max(n ? 1 : 0, Math.round(n * scale));
  const QUESTIONS = [
    { id: "same|mueller", kind: "same_name", letters_only: false, files: ["Patienten.xlsx", "Follow-up.sav", "Briefe/Arztbrief_Mueller.docx", "notes.txt"], columns: [], finding_ids: ["PERSON:0"],
      text: "Max Müller appears with no birth date or ID in 4 files. Is this the same person as Max Müller (born 12.05.1961; ID P-10037)?",
      options: [{ value: "same", label: "Yes, the same person" }, { value: "different", label: "No, someone else" }, { value: "unsure", label: "I do not know" }] },
    { id: "column|Patienten.xlsx|Stammdaten|7", kind: "column", letters_only: false, files: ["Patienten.xlsx"], columns: [["Patienten.xlsx", "Stammdaten", 7]], finding_ids: [],
      text: "Patienten.xlsx, Stammdaten, column H has no header, and its values look like dates. What is it?",
      options: [{ value: "birth", label: "Birth dates" }, { value: "date", label: "Other dates" }, { value: "keep", label: "Nothing personal, keep it" }] },
    { id: "mention|smith", kind: "mention", letters_only: true, files: ["Briefe/discharge_letter_03.pdf"], columns: [], finding_ids: ["PERSON:1"],
      text: "\"Mr Smith\" appears in discharge_letter_03.pdf with only a surname. Is this the patient James Smith (born 1954)?",
      options: [{ value: "yes", label: "Yes" }, { value: "no", label: "No, another person" }] },
  ];
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
  const TABLES = [
    { title: "Patienten.xlsx: Stammdaten", unit: "patients", total: 412, characteristics: ["sex", "age", "OP-Datum", "Entlassdatum"] },
    { title: "Follow-up.sav", unit: "patients", total: 398, characteristics: ["sex", "age", "date_followup"] },
    { title: "outcomes.csv", unit: "rows", total: 1260, characteristics: ["sex", "death_date"] },
    { title: "Linked by patient code", unit: "patients", total: 412, characteristics: ["sex", "age", "OP-Datum", "Entlassdatum", "date_followup", "death_date"] },
  ];
  const SHARE = { 1: [86.4, 71.1, 12.5, 97.3], 2: [61.2, 40.5, 6.1, 78.4], 3: [7.3, 3.5, 0.4, 9.2], 4: [0, 0, 0, 0] };
  const LETTERS = FILES.filter(f => f.kind !== "table" && !f.left).map(f => f.path);
  const decided = { '["Patienten.xlsx","Kontakt",5]': "KEEP" };  // what the user said a column counts as; one is set from the start
  let projects = want === "empty" ? [] : [
    { id: "p1", name: "Studie", path: "/Users/demo/Documents/Studie", available: true },
    { id: "p2", name: "TAVI Registry 2024", path: "/Users/demo/Documents/TAVI Registry 2024", available: true },
    { id: "p3", name: "Alte Daten", path: "/Volumes/Extern/Alte Daten", available: false },
  ];
  const session = { id: null, extra: [], keep: [], selected: READY.slice(), usedAi: true, job: "", step: 0 };

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
        left_out: n >= 3 ? LETTERS.filter(f => session.selected.includes(f)) : [],
        blanked_rows: n === 4 ? 23 : 0, label, anonymous, reasons, min_group: 5 };
    }
    return out;
  }

  function scanResult() {
    const on = new Set(session.selected);
    const keep = new Set(session.keep);
    const used = new Map();   // finding id -> the finding, with the files it is in
    const outline = {};
    const small = session.id === "p1" ? 1 : 0.4;
    const note = (f, path) => { if (!used.has(f.id)) used.set(f.id, { ...f, files: [], count: 0, questions: QUESTIONS.filter(q => q.finding_ids.includes(f.id)).map(q => q.id), kept: keep.has(f.id) }); const u = used.get(f.id); if (!u.files.includes(path)) u.files.push(path); return u; };
    const values = (type, n, path, shift) => Array.from({ length: Math.round(many(n) * small) }, (_, i) => { const u = note(finding(type, i + (shift || 0)), path); const count = 1 + (i * 7) % 5; u.count += count; return { id: u.id, count }; });
    FILES.forEach((file, fileAt) => {
      if (file.left || !on.has(file.path)) return;
      const tables = (file.tables || []).map(t => ({ name: t.name, columns: t.columns.map(([header, kind, n, inside], i) => {
        const ref = [file.path, t.name, i];
        const choice = decided[JSON.stringify(ref)];
        const now = choice || kind;
        const empty = now === "KEEP";
        return { ref, header, kind: now, kind_label: KINDS[now][0], becomes: KINDS[now][1], values: empty ? [] : values(inside || (KINDS[now][2] ? now : kind), n, file.path, kind === "PERSON" && fileAt ? 2 : 0),
          choices: ["INSURANCE", "TEXT"].includes(kind) ? [] : CHOICES, decided: choice || null, questions: QUESTIONS.filter(q => q.columns.some(c => JSON.stringify(c) === JSON.stringify(ref))).map(q => q.id) };
      }) }));
      const groups = (file.groups || []).map(([type, n]) => ({ type, label: KINDS[type][2], becomes: KINDS[type][1], values: values(type, n, file.path, 0), questions: [] })).filter(g => g.values.length);
      outline[file.path] = { tables, groups };
    });
    // A word with "none" in it is not found, one with "done" was already replaced.
    const added = session.extra.map((term, i) => {
      const count = /none|done/i.test(term) ? 0 : 3 + i * 4;
      const files = count ? session.selected.slice(0, 1 + i % 4) : [];
      const f = { id: `TERM:${term}`, type: "TERM", label: "Word added by you", value: term, count, already_replaced: /done/i.test(term) ? 5 : 0, becomes: `TERM_${four(i + 1)}`,
        files, source: "added", can_keep: false, keep_reason: "You added this word yourself. Remove it below if it should stay.", kept: false, questions: [] };
      files.forEach(path => { const o = outline[path]; if (!o) return; let g = o.groups.find(x => x.type === "TERM"); if (!g) o.groups.push(g = { type: "TERM", label: "Words added by you", becomes: "a code", values: [], questions: [] }); g.values.push({ id: f.id, count: Math.max(1, Math.round(count / files.length)) }); });
      return f;
    });
    const all = [...used.values(), ...added];
    const project = projects.find(p => p.id === session.id);
    const questions = QUESTIONS.filter(q => q.files.some(p => on.has(p)));
    return {
      project: session.id, folder: project.name, path: project.path, single: false, used_ai: session.usedAi,
      tables: FILES.filter(f => f.kind === "table" && on.has(f.path)).length, other_files: FILES.filter(f => f.kind !== "table" && on.has(f.path)).length,
      unsupported: FILES.filter(f => f.left).map(f => f.path), named_files: 1, questions,
      notes: ["Briefe/Arztbrief_Mueller.docx: the file name contains a name from the data. File names are never changed, so look before you upload.",
        "Patienten.xlsx: 2 formulas use an identifying column, so their stored results are removed.",
        "Briefe/discharge_letter_03.pdf becomes a text file, discharge_letter_03.pdf.md."],
      columns: COLUMNS, has_key: query.get("haskey") !== "0" && session.id === "p1" || session.madeKey === session.id, levels: LEVELS, preview: preview({}, [], []), findings: all, outline,
      files: FILES.map(f => ({ path: f.path, name: base(f.path), kind: f.kind, found: all.filter(x => x.files.includes(f.path)).length,
        questions: f.left || !on.has(f.path) ? 0 : questions.filter(q => q.files.includes(f.path)).length,
        status: f.left ? "left_out" : "ready", reason: f.left || null, selected: !f.left && on.has(f.path) })),
    };
  }

  const STATUS = { scan: ["Loading the local AI model", "Reading your files · File 1 of 8", "Reading your files · File 3 of 8", "Reading your files · File 6 of 8", "Reading your files · File 8 of 8", "Working out who is who"],
    export: ["Writing the copy and checking it", "Writing the copy · File 2 of 8", "Writing the copy · File 7 of 8", "Checking the files as written"],
    restore: ["Opening the key", "Putting the real values back"] };

  window.pywebview = { api: {
    async startup() { await wait(150); return { ai_ready: want !== "noai", version: "0.1 demo", projects }; },
    async add_project() {
      await wait(300);
      const id = "p" + (projects.length + 1 + Math.floor(rnd() * 1000));
      projects = [...projects, { id, name: "Neue Studie", path: "/Users/demo/Documents/Neue Studie", available: true }];
      return { projects, added: id };
    },
    async add_project_paths(paths) {
      await wait(200);
      if (paths.some(p => /\.\w+$/.test(p))) return { error: "Please add a folder, not a single file." };
      const id = "p" + (projects.length + 1 + Math.floor(rnd() * 1000));
      projects = [...projects, { id, name: base(paths[0]), path: paths[0], available: true }];
      return { projects, added: id };
    },
    async remove_project(id) { await wait(150); projects = projects.filter(p => p.id !== id); return { projects }; },
    async choose(kind) {
      await wait(300);
      if (kind === "files") return ["/Users/demo/Downloads/results.docx", "/Users/demo/Downloads/table_1.xlsx"];
      return ["/Users/demo/Documents/Ergebnisse"];
    },
    async status() { if (!session.job) return ""; const list = STATUS[session.job]; session.step += 1; return list[Math.min(list.length - 1, Math.floor(session.step / 2))]; },
    async open_project(id, useAi) {
      session.job = "scan"; session.step = 0;
      await wait(want === "busy" ? 600000 : 3600);
      session.job = "";
      if (want === "error") return { error: "Nothing in this folder could be read. Privatier reads Excel, SPSS, CSV, Word, PDF and text files." };
      session.id = id; session.usedAi = Boolean(useAi); session.extra = []; session.keep = []; session.selected = READY.slice();
      return scanResult();
    },
    async set_files(selected) { await wait(1200); session.selected = selected.slice(); return scanResult(); },
    async set_column(ref, value) {
      await wait(900);
      if (value == null) delete decided[JSON.stringify(ref)]; else decided[JSON.stringify(ref)] = value;
      return scanResult();
    },
    async review(keep, extra) {
      await wait(700);
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
      const name = { 1: "pseudonymised", 2: "less_detail", 3: "strongly_reduced", 4: "level4" }[level];
      const root = projects.find(x => x.id === session.id).path + "/Privatier";
      if (LEVELS[level - 1].keeps_key) session.madeKey = session.id;
      return { worst: p.worst, tables: p.tables, could_not_check: p.could_not_check, output: `${root}/${name}`, output_name: name, label: p.label, anonymous: p.anonymous,
        reasons: p.reasons, processed: 8, kept: (keep || []).length,
        skipped: [{ file: "scan_0001.jpg", reason: "images are not supported yet" }, { file: "alte_Liste.xls", reason: "old Excel files are not supported yet" },
          ...p.left_out.map(f => ({ file: f, reason: "letters are left out at this level" }))],
        errors: level === 2 ? [{ file: "Labor_defekt.xlsx", reason: "this file could not be processed, so it is not in the copy" }] : [],
        notes: ["Patienten.xlsx: 2 stored formula results were removed, as they could reveal the data.", "privacy_report.txt lists what was changed, with counts and column names only."],
        report: `${root}/key/privacy_report.txt`, key_dir: LEVELS[level - 1].keeps_key ? `${root}/key` : null };
    },
    async restore_info(paths) {
      await wait(400);
      if (paths.some(p => /empty/i.test(p))) return { error: "There is nothing in this folder that Privatier can read." };
      return { name: paths.length > 1 ? `${paths.length} files` : base(paths[0]), files: paths.length > 1 ? paths.length : 6 };
    },
    async restore(paths, password) {
      session.job = "restore"; session.step = 0;
      await wait(2600);
      session.job = "";
      if (password === "wrongpass") return { error: "This is not the password of this project's key." };
      return { output: projects.find(x => x.id === session.id).path + "/Privatier/restored/" + base(paths[0]), restored: 5, values: 1284, unknown: 2,
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
  const stageShown = (sheet, name) => new Promise(done => { const t = setInterval(() => {
    if (!document.querySelector(`#sheet-${sheet} [data-stage="${name}"]`).classList.contains("hidden")) { clearInterval(t); done(); } }, 50); });
  window.addEventListener("load", async () => {
    window.dispatchEvent(new Event("pywebviewready"));
    const click = id => document.getElementById(id).click();
    const type = (id, value) => { const el = document.getElementById(id); el.value = value; el.dispatchEvent(new Event("input", { bubbles: true })); };
    if (["start", "empty"].includes(want)) return;
    await wait(400);
    const row = document.querySelector(`#project-list [data-id="${want === "nokey" ? "p2" : "p1"}"]`);
    if (row) row.click();
    if (["busy", "error"].includes(want)) return;
    await shown("sheet-setup");
    if (want === "protection" || want === "noai") return;
    if (want === "points") { click("setup-continue"); return; }
    click("setup-done");
    if (want === "open") {
      const pick = path => document.querySelector(`#file-list [data-path="${path}"]`).click();
      pick("Patienten.xlsx");
      const tris = () => [...document.querySelectorAll("#outline-rows .tri")];
      tris()[1].click();                                           // the Name column
      document.querySelectorAll("#outline-rows .val input")[2].click();   // one value kept as written
      return;
    }
    if (want === "copy" || want === "result") click("copy-button");
    if (want === "result") { type("password", "demo-password"); type("password2", "demo-password"); click("copy-go"); }
    if (["restore", "restored", "nokey"].includes(want)) click("restore-button");
    if (want === "restored") {
      window.itemsDropped(["/Users/demo/Documents/Ergebnisse"]);
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
    print("Jump to a screen by adding for example ?state=project or ?state=level&theme=dark to the address.")
    if "--open" in arguments:
        webbrowser.open(target.as_uri())


if __name__ == "__main__":
    main(sys.argv[1:])
