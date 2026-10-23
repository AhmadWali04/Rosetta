const pptxgen = require("pptxgenjs");
const { applyTheme } = require("/Users/ahmadwali04/Library/Application Support/Claude/local-agent-mode-sessions/skills-plugin/372c52fe-3dbc-4267-9337-7f025f286d9d/d87e8f18-a038-4146-bf65-32d4043fd297/skills/pptx/scripts/apply_theme.js");

const OUT = process.argv[2] || "Rosetta-ProCogia.pptx";

// Palette: ink + deep teal (evidence / grounded) + amber (risk / failure)
const HEX = {
  ink: "1F2A37", bg: "F7F8FA", white: "FFFFFF", muted: "5B6472", line: "D9DEE5",
  teal: "0F766E", tealLight: "E3F1EF", amber: "B45309", amberLight: "FBEEDC", card: "FFFFFF", soft: "EEF1F5",
};
const THEME = {
  name: "Rosetta",
  headFontFace: "Arial",
  bodyFontFace: "Arial",
  colors: {
    dk1: HEX.ink, lt1: HEX.white, dk2: "374151", lt2: HEX.bg,
    accent1: HEX.teal, accent2: HEX.amber, accent3: "64748B", accent4: "94A3B8", accent5: "0E7490", accent6: "A16207",
    hlink: HEX.teal, folHlink: "115E59",
  },
};

const pres = new pptxgen();
pres.layout = "LAYOUT_16x9"; // 10 x 5.625
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
pres.title = "Rosetta: evidence-cited technical screening";
pres.author = "Ahmad Wali";

const FONT = "Arial";

pres.defineSlideMaster({
  title: "DARK",
  background: { color: HEX.ink },
  objects: [],
});
pres.defineSlideMaster({
  title: "CONTENT",
  background: { color: HEX.bg },
  objects: [
    { placeholder: { options: { name: "kicker", type: "body", x: 0.5, y: 0.28, w: 9, h: 0.3, fontFace: FONT, fontSize: 11, bold: true, color: HEX.teal, margin: 0, valign: "top", align: "left" }, text: "" } },
    { placeholder: { options: { name: "title", type: "title", x: 0.5, y: 0.55, w: 9, h: 0.9, fontFace: FONT, fontSize: 26, bold: true, color: HEX.ink, margin: 0, valign: "top", align: "left" }, text: "" } },
  ],
  slideNumber: { x: 9.1, y: 5.25, w: 0.4, h: 0.25, fontFace: FONT, fontSize: 9, color: "8A93A0", align: "right" },
});

// ---------- helpers ----------
function content(kicker, title) {
  const s = pres.addSlide({ masterName: "CONTENT" });
  s.addText(kicker.toUpperCase(), { placeholder: "kicker" });
  s.addText(title, { placeholder: "title" });
  return s;
}
function text(s, t, o) {
  s.addText(t, Object.assign({ fontFace: FONT, fontSize: 14, color: HEX.ink, isTextBox: true, valign: "top", margin: 0 }, o));
}
function card(s, x, y, w, h, fill, opts = {}) {
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x, y, w, h, rectRadius: 0.08, fill: { color: fill || HEX.card },
    line: { color: opts.line || HEX.line, width: opts.lineW || 0.75 },
  });
}
function box(s, x, y, w, h, label, o = {}) {
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x, y, w, h, rectRadius: 0.06,
    fill: { color: o.fill || HEX.white }, line: { color: o.line || HEX.line, width: 1 },
  });
  s.addText(label, {
    x, y, w, h, fontFace: FONT, fontSize: o.size || 11, bold: o.bold !== false, color: o.color || HEX.ink,
    align: "center", valign: "middle", margin: 3, isTextBox: true,
  });
}
function arrow(s, x1, y1, x2, y2, o = {}) {
  s.addShape(pres.shapes.LINE, {
    x: Math.min(x1, x2), y: Math.min(y1, y2), w: Math.abs(x2 - x1) || 0.0001, h: Math.abs(y2 - y1) || 0.0001,
    flipH: x2 < x1, flipV: y2 < y1,
    line: { color: o.color || "7B8594", width: o.width || 1.25, endArrowType: o.noHead ? undefined : "triangle", dashType: o.dash },
  });
}
function numDot(s, x, y, n, fill) {
  s.addShape(pres.shapes.OVAL, { x, y, w: 0.38, h: 0.38, fill: { color: fill || HEX.teal }, line: { color: fill || HEX.teal } });
  s.addText(String(n), { x, y, w: 0.38, h: 0.38, fontFace: FONT, fontSize: 13, bold: true, color: HEX.white, align: "center", valign: "middle", margin: 0, isTextBox: true });
}
function footnote(s, t) {
  text(s, t, { x: 0.5, y: 5.2, w: 8.5, h: 0.3, fontSize: 9, color: "7A8391" });
}
function table(s, rows, o) {
  const head = rows[0].map((c) => ({ text: c, options: { bold: true, color: HEX.ink, fill: { color: HEX.bg } } }));
  const body = rows.slice(1).map((r, ri) =>
    r.map((c, ci) => {
      const hl = o.highlightRow === ri + 1;
      return { text: c, options: { bold: ci === 0, color: hl && o.hlColor ? o.hlColor : HEX.ink, fill: { color: hl ? (o.hlFill || HEX.tealLight) : HEX.white } } };
    })
  );
  s.addTable([head, ...body], Object.assign({
    fontFace: FONT, fontSize: 12, valign: "middle", margin: [3, 6, 3, 6],
    border: [{ type: "none" }, { type: "none" }, { pt: 0.75, color: HEX.line }, { type: "none" }],
  }, o));
}
function bullets(items, size = 14) {
  return items.map((t, i) => {
    const runs = Array.isArray(t) ? t : [{ text: t }];
    return runs.map((r, j) => ({
      text: r.text,
      options: Object.assign(
        { fontSize: size, color: HEX.ink },
        j === 0 ? { bullet: { indent: 14 }, paraSpaceAfter: 6 } : {},
        r.bold ? { bold: true } : {},
        j === runs.length - 1 && i < items.length - 1 ? { breakLine: true } : {}
      ),
    }));
  }).flat();
}

// ---------- 1. Title ----------
{
  const s = pres.addSlide({ masterName: "DARK" });
  text(s, "Rosetta", { x: 0.7, y: 1.05, w: 8.6, h: 0.95, fontSize: 54, bold: true, color: HEX.white });
  text(s, "Evidence-cited technical screening for non-technical recruiters", { x: 0.7, y: 2.0, w: 8.6, h: 0.5, fontSize: 22, color: "D6DCE4" });
  // translation motif: resume phrase -> canonical skill -> JD requirement
  const chips = [["Resume line", "“built ETL jobs in PySpark”"], ["Canonical skill", "Data pipelines (O*NET)"], ["JD requirement", "Met, with citation"]];
  chips.forEach(([k, v], i) => {
    const x = 0.7 + i * 2.95;
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y: 3.0, w: 2.55, h: 0.85, rectRadius: 0.08, fill: { color: "2B3A4C" }, line: { color: "3D5068", width: 0.75 } });
    text(s, k.toUpperCase(), { x: x + 0.15, y: 3.1, w: 2.3, h: 0.25, fontSize: 10, bold: true, color: "5EC4B6" });
    text(s, v, { x: x + 0.15, y: 3.37, w: 2.3, h: 0.4, fontSize: 13, color: HEX.white });
    if (i < 2) arrow(s, x + 2.6, 3.42, x + 2.9, 3.42, { color: "5EC4B6" });
  });
  text(s, "Ahmad Wali  ·  ProCogia AI Intern technical assessment  ·  October 2026", { x: 0.7, y: 4.6, w: 8.6, h: 0.35, fontSize: 13, color: "AEB7C3" });
  s.addNotes("Rosetta (working name SkillBridge) is a three-portal hiring app: Applicant, HR, Technical Lead. A LangGraph multi-agent system turns each resume into a skill profile where every claim is cited to a resume line.");
}

// ---------- 2. Executive summary ----------
{
  const s = content("Overview", "Executive summary");
  const rows = [
    ["Problem", "Recruiters can’t judge technical fit, and tech leads don’t trust the shortlist, so they re-screen every applicant."],
    ["Solution", "A LangGraph system that cites every skill claim to a resume line: a fixed nine-step intake pipeline plus a routed recruiter copilot."],
    ["Status", "Intake, HR portal and copilot are built. 299 backend and 28 frontend tests pass against a fake model."],
    ["Gap", "No live-model run has completed (OpenAI quota), and the evaluation scorecard and Tech Lead portal are not built yet."],
  ];
  rows.forEach(([k, v], i) => {
    const y = 1.6 + i * 0.88;
    card(s, 0.5, y, 9, 0.74, i === 3 ? HEX.amberLight : HEX.white, { line: i === 3 ? "EBCFA8" : HEX.line });
    numDot(s, 0.68, y + 0.18, i + 1, i === 3 ? HEX.amber : HEX.teal);
    text(s, k, { x: 1.25, y: y + 0.12, w: 1.4, h: 0.5, fontSize: 15, bold: true, valign: "middle" });
    text(s, v, { x: 2.6, y: y + 0.1, w: 6.7, h: 0.55, fontSize: 14, valign: "middle" });
  });
}

// ---------- 3. Problem ----------
{
  const s = content("1 · Problem and business value", "Recruiters and tech leads fail each other on two gaps");
  const cols = [
    ["VOCABULARY GAP", "Recruiter (HR)", "Can’t tell whether “built ETL in PySpark” satisfies “experience with data pipelines”, or whether “LangChain” implies agent orchestration.", "Falls back on keyword matching."],
    ["TRUST GAP", "Technical lead", "Receives hundreds of applicants, many keyword-stuffed. HR’s shortlist shows no reasoning or evidence.", "Re-screens every applicant."],
  ];
  cols.forEach(([tag, who, pain, result], i) => {
    const x = 0.5 + i * 4.65;
    card(s, x, 1.6, 4.35, 2.55);
    text(s, tag, { x: x + 0.25, y: 1.78, w: 3.9, h: 0.25, fontSize: 11, bold: true, color: HEX.teal });
    text(s, who, { x: x + 0.25, y: 2.05, w: 3.9, h: 0.4, fontSize: 20, bold: true });
    text(s, pain, { x: x + 0.25, y: 2.55, w: 3.9, h: 1.0, fontSize: 14, color: "374151" });
    text(s, result, { x: x + 0.25, y: 3.62, w: 3.9, h: 0.35, fontSize: 14, bold: true, color: HEX.amber });
  });
  card(s, 0.5, 4.35, 9, 0.7, HEX.soft, { line: HEX.soft });
  text(s, [
    { text: "Keyword filters make both gaps worse: ", options: { bold: true } },
    { text: "they reject strong candidates who use different words and pass weak candidates who copy the job description." },
  ], { x: 0.75, y: 4.43, w: 8.5, h: 0.55, fontSize: 14, valign: "middle" });
}

// ---------- 4. Success metrics ----------
{
  const s = content("1 · Problem and business value", "Success means HR can defend a shortlist and the tech lead audits it in minutes");
  const tiles = [
    ["< 3 min", "tech-lead review per candidate, instead of a full re-screen"],
    ["≥ 95%", "of AI claims carry a valid citation that supports them"],
    ["κ ≥ 0.6", "agreement between AI tier and human tier (Cohen’s kappa)"],
    ["100%", "of prompt-injection resumes flagged; no stuffed resume in Advance"],
  ];
  tiles.forEach(([big, label], i) => {
    const x = 0.5 + i * 2.3;
    card(s, x, 1.65, 2.1, 2.05);
    text(s, big, { x: x + 0.18, y: 1.85, w: 1.8, h: 0.7, fontSize: 32, bold: true, color: HEX.teal });
    text(s, label, { x: x + 0.18, y: 2.6, w: 1.8, h: 1.0, fontSize: 13, color: "374151" });
  });
  text(s, [
    { text: "Business value for ProCogia: ", options: { bold: true } },
    { text: "Rosetta is the missing Technical Screening agent next to Haigent’s sourcing and scheduling agents, built on the same principles: LangGraph, human approval gates and a full audit trail. The AI recommends; people decide." },
  ], { x: 0.5, y: 3.95, w: 9, h: 0.9, fontSize: 14 });
  footnote(s, "Targets set in the project PRD (§3, §11). They have not been measured with a live model yet; see the evaluation section.");
}

// ---------- 5. Why multi-agent ----------
{
  const s = content("1 · Problem and business value", "Each agent owns one checkable judgment, so a failure stays local");
  const agents = [
    ["Sanitizer", "Strips hidden text and flags injected instructions before any model reads the resume"],
    ["Skill extractor", "Pulls each skill with its evidence span and depth: listed, coursework, project or production"],
    ["Skill normalizer", "Maps aliases to canonical skills through taxonomy RAG"],
    ["Requirement matcher", "Judges met, partial or missing per requirement and must cite chunk IDs"],
    ["Scorer", "Applies fixed, configurable weights; no LLM, so scores are reproducible"],
    ["HR explainer", "Rewrites each verdict in plain English for a non-technical reader"],
  ];
  agents.forEach(([n, d], i) => {
    const col = i % 3, row = Math.floor(i / 3);
    const x = 0.5 + col * 3.05, y = 1.6 + row * 1.42;
    card(s, x, y, 2.85, 1.25);
    text(s, n, { x: x + 0.2, y: y + 0.14, w: 2.5, h: 0.3, fontSize: 15, bold: true, color: HEX.teal });
    text(s, d, { x: x + 0.2, y: y + 0.48, w: 2.5, h: 0.72, fontSize: 12, color: "374151" });
  });
  text(s, "One large prompt would mix untrusted resume text with judgment and explanation, and leave no point at which to check a citation.", { x: 0.5, y: 4.55, w: 9, h: 0.55, fontSize: 14, italic: true, color: "374151" });
}

// ---------- 6. Data sources ----------
{
  const s = content("2 · Data, RAG and vector database", "Four public sources and one synthetic set, each chosen for one job");
  table(s, [
    ["Source", "Why chosen", "Preparation", "Limitation"],
    ["ProCogia AI Intern posting", "The real target role", "10 requirements, must/nice split, weights", "Weights are my judgment; one job only"],
    ["O*NET Technology Skills", "Public canonical skill names", "114 curated skills", "Subset of thousands"],
    ["ESCO skills", "Open taxonomy with synonyms", "56 curated skills with alt labels", "Subset of thousands"],
    ["Synthetic resumes", "Hit specific tiers and attacks", "Strong, different-vocabulary, stuffed, injection", "Not a real applicant distribution"],
    ["GitHub REST API", "Public evidence for Deep Verify", "github.com users only, ≤ 10 repos, 5 s timeout", "Supplements, never replaces, a resume citation"],
  ], { x: 0.5, y: 1.55, w: 9, colW: [2.15, 2.15, 2.45, 2.25], rowH: 0.52, fontSize: 12 });
  footnote(s, "Posting cross-checked against two Greenhouse-sourced mirrors. Taxonomy: 170 skills in data/taxonomy/skills.json.");
}

// ---------- 7. Retrieval pipeline ----------
{
  const s = content("2 · Data, RAG and vector database", "Hybrid retrieval catches exact tool names and paraphrased experience");
  const steps = [
    ["Chunk", "Section-aware, 300 tokens with 50 overlap; never crosses a section"],
    ["Embed", "Dense llama-text-embed-v2 (1024-d) plus sparse English vectors"],
    ["Query", "Top 20 from each index, filtered to one applicant"],
    ["Fuse", "Reciprocal rank fusion (k = 60), keep top 5; rerank off by default"],
    ["Cite", "Text hydrated from Postgres; the LLM must cite chunk IDs"],
  ];
  steps.forEach(([n, d], i) => {
    const x = 0.5 + i * 1.84;
    card(s, x, 1.6, 1.62, 2.0, i === 4 ? HEX.tealLight : HEX.white, { line: i === 4 ? "B7DCD6" : HEX.line });
    numDot(s, x + 0.15, 1.75, i + 1);
    text(s, n, { x: x + 0.62, y: 1.78, w: 0.95, h: 0.32, fontSize: 15, bold: true });
    text(s, d, { x: x + 0.15, y: 2.25, w: 1.36, h: 1.3, fontSize: 12, color: "374151" });
    if (i < 4) arrow(s, x + 1.64, 2.6, x + 1.82, 2.6);
  });
  const ex = [
    ["Sparse index catches exact tokens", "“dbt”, “k8s”, “Langfuse”, version numbers"],
    ["Dense index catches paraphrase", "“built ETL jobs”  ↔  “data pipelines”"],
  ];
  ex.forEach(([h, d], i) => {
    const x = 0.5 + i * 4.6;
    card(s, x, 3.85, 4.4, 0.95, HEX.soft, { line: HEX.soft });
    text(s, h, { x: x + 0.2, y: 3.95, w: 4.0, h: 0.3, fontSize: 14, bold: true });
    text(s, d, { x: x + 0.2, y: 4.3, w: 4.0, h: 0.4, fontSize: 14, color: "374151" });
  });
  footnote(s, "Two Pinecone serverless indexes (dense cosine, sparse dot product) with namespaces per environment and job: taxonomy, JD, resume chunks, candidate summaries.");
}

// ---------- 8. Data quality ----------
{
  const s = content("2 · Data, RAG and vector database", "Resume text is treated as untrusted; taxonomy size and parsing are the weak points");
  const left = [
    "Hidden and white text stripped before indexing",
    "17-rule injection detector plus an LLM check, run before chunking",
    "Postgres is the source of truth; Pinecone can be rebuilt from it",
    "Vector audit checks dense and sparse parity per namespace",
    "15 s freshness wait; on timeout the matcher uses in-state chunks",
  ];
  const right = [
    "Taxonomy is 170 curated skills, not the full O*NET and ESCO sets",
    "Section detection is a keyword heuristic",
    "Resumes are synthetic, so no evidence on real applicants yet",
    "Local mode uses fake embeddings (Pinecone Local hosts no models)",
    "Requirement weights are judgment calls that HR can edit",
  ];
  [["What the pipeline guards", left, HEX.white, HEX.teal], ["Known limitations", right, HEX.amberLight, HEX.amber]].forEach(([h, items, fill, col], i) => {
    const x = 0.5 + i * 4.6;
    card(s, x, 1.6, 4.4, 3.45, fill, { line: i ? "EBCFA8" : HEX.line });
    text(s, h, { x: x + 0.25, y: 1.75, w: 3.9, h: 0.35, fontSize: 16, bold: true, color: col });
    s.addText(bullets(items, 13), { x: x + 0.25, y: 2.2, w: 3.95, h: 2.75, fontFace: FONT, valign: "top", margin: 0, isTextBox: true });
  });
}

// ---------- 9. Static intake ----------
{
  const s = content("3 · Architecture, agent skills and workflows", "Static workflow: every application runs the same nine steps");
  const nodes = [
    ["Ingest & parse", "rules"], ["Sanitize & injection check", "rules + LLM"], ["Chunk & index", "Postgres + Pinecone"],
    ["Skill extractor", "LLM"], ["Skill normalizer", "RAG: taxonomy"], ["Requirement matcher", "RAG: resume, cites"],
    ["Scorer", "weights, no LLM"], ["HR explainer", "LLM"], ["Persist profile", "Postgres + audit"],
  ];
  const llm = new Set([1, 3, 4, 5, 7]);
  nodes.forEach(([n, t], i) => {
    const row = Math.floor(i / 5), col = i % 5;
    const x = 0.5 + col * 1.84, y = 1.65 + row * 1.35;
    const isL = llm.has(i);
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w: 1.6, h: 0.95, rectRadius: 0.06, fill: { color: isL ? HEX.tealLight : HEX.white }, line: { color: isL ? "8FCBC2" : HEX.line, width: 1 } });
    text(s, n, { x: x + 0.08, y: y + 0.1, w: 1.44, h: 0.5, fontSize: 12, bold: true, align: "center", valign: "middle" });
    text(s, t, { x: x + 0.08, y: y + 0.6, w: 1.44, h: 0.28, fontSize: 10, color: HEX.muted, align: "center" });
    if (col < 4 && i < 8) arrow(s, x + 1.62, y + 0.47, x + 1.82, y + 0.47);
  });
  // wrap arrow from node 5 (row0 col4) to node 6 (row1 col0)
  arrow(s, 0.5 + 4 * 1.84 + 0.8, 2.6, 0.5 + 4 * 1.84 + 0.8, 2.8, { noHead: true });
  arrow(s, 0.5 + 4 * 1.84 + 0.8, 2.8, 1.3, 2.8, { noHead: true });
  arrow(s, 1.3, 2.8, 1.3, 3.0);
  text(s, "Teal = model or retrieval step", { x: 7.88, y: 3.25, w: 1.6, h: 0.5, fontSize: 10, color: HEX.muted });
  card(s, 0.5, 4.15, 9, 0.9, HEX.soft, { line: HEX.soft });
  text(s, [
    { text: "Score = 0.50 must-have + 0.20 nice-to-have + 0.15 semantic similarity + 0.15 depth − penalties", options: { bold: true, breakLine: true } },
    { text: "Advance ≥ 0.70 · Review 0.45–0.70 · Decline < 0.45. Low confidence, injection or stuffing forces Review. Nothing is rejected automatically." },
  ], { x: 0.7, y: 4.22, w: 8.6, h: 0.78, fontSize: 13, valign: "middle" });
}

// ---------- 10. Dynamic copilot ----------
{
  const s = content("3 · Architecture, agent skills and workflows", "Dynamic workflow: the copilot routes by question and branches on results");
  const H = 0.4;
  box(s, 0.5, 2.85, 1.15, 0.6, "HR question", { fill: HEX.soft, line: HEX.soft });
  box(s, 1.95, 2.85, 1.25, 0.6, "Supervisor (LLM router)", { fill: HEX.tealLight, line: "8FCBC2" });
  box(s, 3.5, 2.85, 1.2, 0.6, "Gather scoped evidence");
  arrow(s, 1.65, 3.15, 1.95, 3.15);
  arrow(s, 3.2, 3.15, 3.5, 3.15);
  const routes = ["Verify claim", "Compare / rank", "Find similar", "Explain skill", "Interview questions", "Update status"];
  routes.forEach((r, i) => {
    const y = 1.55 + i * 0.5;
    box(s, 5.05, y, 1.45, H, r, { size: 11, fill: i === 5 ? HEX.amberLight : HEX.white, line: i === 5 ? "EBCFA8" : HEX.line });
    arrow(s, 4.7, 3.15, 5.05, y + H / 2, { width: 0.75 });
  });
  // deep verify loop
  box(s, 7.0, 1.4, 1.25, 0.6, "Deep Verify (GitHub API)", { size: 10 });
  arrow(s, 6.5, 1.68, 7.0, 1.6, { width: 1 });
  arrow(s, 7.0, 1.85, 6.5, 1.82, { width: 1 });
  text(s, "confidence < 0.7, once", { x: 7.0, y: 2.05, w: 1.6, h: 0.25, fontSize: 9, color: HEX.muted });
  // grounding
  box(s, 7.0, 2.85, 1.25, 0.6, "Grounding check", { fill: HEX.tealLight, line: "8FCBC2" });
  [0, 1, 2, 3, 4].forEach((i) => arrow(s, 6.5, 1.55 + i * 0.5 + H / 2, 7.0, 3.15, { width: 0.75 }));
  box(s, 8.55, 2.85, 0.95, 0.6, "Cited answer", { fill: HEX.ink, line: HEX.ink, color: HEX.white });
  arrow(s, 8.25, 3.15, 8.55, 3.15);
  // HITL
  box(s, 7.0, 4.05, 0.9, 0.5, "HR approves", { size: 10, fill: HEX.amberLight, line: "EBCFA8" });
  arrow(s, 6.5, 4.25, 7.0, 4.3);
  text(s, "LangGraph interrupt", { x: 8.3, y: 4.12, w: 1.2, h: 0.3, fontSize: 9, color: HEX.amber });
  // retry path
  arrow(s, 8.12, 3.45, 8.12, 4.85, { noHead: true, color: HEX.amber, dash: "dash" });
  arrow(s, 8.12, 4.85, 2.57, 4.85, { noHead: true, color: HEX.amber, dash: "dash" });
  arrow(s, 2.57, 4.85, 2.57, 3.45, { color: HEX.amber, dash: "dash" });
  text(s, "Uncited claim → back to supervisor (max 2 retries), then omitted with “couldn’t verify”", { x: 2.75, y: 4.9, w: 5.4, h: 0.28, fontSize: 10, color: HEX.amber });
  text(s, "Route chosen by the request", { x: 3.5, y: 1.55, w: 1.45, h: 0.5, fontSize: 10, color: HEX.muted });
}

// ---------- 11. Tools and shared state ----------
{
  const s = content("3 · Architecture, agent skills and workflows", "Agents exchange typed state and call nine scoped, reusable tools");
  card(s, 0.5, 1.6, 3.0, 3.45, HEX.ink, { line: HEX.ink });
  text(s, "Shared state", { x: 0.72, y: 1.75, w: 2.6, h: 0.35, fontSize: 16, bold: true, color: HEX.white });
  s.addText(bullets([
    "Pydantic models: IntakeState and CopilotState",
    "Each node returns a partial update; it never edits another node’s output",
    "Fields carry evidence, claims, confidence, warnings, steps and retries",
    "Checkpointed in Postgres per application or copilot run",
  ], 12).map((r) => (r.options.color = "E5E9EF", r)), { x: 0.72, y: 2.2, w: 2.62, h: 2.75, fontFace: FONT, valign: "top", margin: 0, isTextBox: true });
  const tools = [
    ["search_resume_chunks", "Hybrid search inside one applicant"], ["search_taxonomy", "Canonical skill lookup"],
    ["get_jd_requirements", "Requirements with weights"], ["get_candidate_profile", "Stored profile for one job"],
    ["rank_pool", "Saved ranking inputs"], ["find_similar", "Peers via summary vectors"],
    ["validate_citations", "Resolve chunk IDs in Postgres"], ["github_profile", "Public repos and languages"],
    ["update_status", "Write tool: needs HR approval"],
  ];
  tools.forEach(([n, d], i) => {
    const col = i % 2, row = Math.floor(i / 2);
    const x = 3.8 + col * 2.88, y = 1.6 + row * 0.7;
    const w = i === 8 ? 5.7 : 2.72;
    const warn = i === 8;
    card(s, x, y, w, 0.58, warn ? HEX.amberLight : HEX.white, { line: warn ? "EBCFA8" : HEX.line });
    text(s, n, { x: x + 0.14, y: y + 0.06, w: w - 0.2, h: 0.24, fontSize: 11, bold: true, color: warn ? HEX.amber : HEX.teal, fontFace: "Courier New" });
    text(s, d, { x: x + 0.14, y: y + 0.3, w: w - 0.2, h: 0.24, fontSize: 11, color: "374151" });
  });
}

// ---------- 12. Routing, errors, stopping ----------
{
  const s = content("3 · Architecture, agent skills and workflows", "Every loop has a hard stop, and every failure is recorded somewhere visible");
  table(s, [
    ["Situation", "What the system does", "Stopping condition or outcome"],
    ["Verifier confidence below 0.7", "Deep Verify calls GitHub, then re-verifies", "At most one Deep Verify per run"],
    ["Claim cites an unprovided chunk", "Grounding rejects it; back to supervisor", "Max 2 retries, then omitted"],
    ["Comparison cites one candidate", "Claim dropped", "Must cite at least two candidates"],
    ["Pinecone upsert fails", "3 retries with backoff", "Marked failed; copilot uses Postgres"],
    ["Vectors not searchable after 15 s", "Matcher uses chunks held in graph state", "Run flagged for review"],
    ["Model or parsing error in intake", "Worker catches it and keeps polling", "intake_failed status plus an audit event"],
    ["Request to change a status", "LangGraph interrupt pauses the run", "Resumes only when HR decides"],
  ], { x: 0.5, y: 1.55, w: 9, colW: [2.9, 3.25, 2.85], rowH: 0.4, fontSize: 12 });
  footnote(s, "Graph recursion limit is 60 steps. Every graph run, label change and confirmation writes an events row.");
}

// ---------- 13. Model + context ----------
{
  const s = content("4 · Model selection and context management", "GPT-4o-mini at temperature 0, behind a swappable provider interface");
  card(s, 0.5, 1.6, 4.3, 3.45);
  text(s, "Why this model", { x: 0.72, y: 1.75, w: 3.9, h: 0.35, fontSize: 16, bold: true, color: HEX.teal });
  s.addText(bullets([
    "Structured output straight into Pydantic models",
    "Intake makes 10 matcher calls per resume alone, so a small model keeps cost per resume low",
    "Temperature 0 keeps scores repeatable across reruns",
    "app/llm is the only code that imports a provider SDK; an Anthropic provider is stubbed",
  ], 13), { x: 0.72, y: 2.2, w: 3.9, h: 2.75, fontFace: FONT, valign: "top", margin: 0, isTextBox: true });
  const stats = [
    ["5", "chunks of evidence per requirement, after fusing two top-20 lists"],
    ["12", "chunks maximum in a copilot answer, split evenly across candidates"],
    ["10", "candidates maximum in pool-level context"],
    ["0", "turns of chat history: each question is a fresh, checkpointed run"],
  ];
  stats.forEach(([b, l], i) => {
    const col = i % 2, row = Math.floor(i / 2);
    const x = 5.05 + col * 2.25, y = 1.6 + row * 1.77;
    card(s, x, y, 2.1, 1.62);
    text(s, b, { x: x + 0.18, y: y + 0.12, w: 1.8, h: 0.6, fontSize: 30, bold: true, color: HEX.teal });
    text(s, l, { x: x + 0.18, y: y + 0.72, w: 1.8, h: 0.85, fontSize: 11, color: "374151" });
  });
  footnote(s, "Resume, GitHub and user text go in delimited data blocks in the user turn, never in the system prompt.");
}

// ---------- 14. Context comparison ----------
{
  const s = content("4 · Model selection and context management", "One call per requirement uses 8× the input tokens of a single combined call");
  const scale = 4.3 / 12875;
  const rowsB = [["A · One call per requirement (current)", 7460, 5415, "12,875"], ["B · One combined call", 746, 862, "1,608"]];
  rowsB.forEach(([lab, ins, ev, tot], i) => {
    const y = 1.9 + i * 1.15;
    text(s, lab, { x: 0.5, y, w: 5.3, h: 0.3, fontSize: 13, bold: true });
    const w1 = ins * scale, w2 = ev * scale;
    s.addShape(pres.shapes.RECTANGLE, { x: 0.5, y: y + 0.35, w: w1, h: 0.5, fill: { color: "94A3B8" }, line: { color: "94A3B8" } });
    s.addShape(pres.shapes.RECTANGLE, { x: 0.5 + w1, y: y + 0.35, w: w2, h: 0.5, fill: { color: HEX.teal }, line: { color: HEX.teal } });
    if (i === 0) {
      text(s, "7,460", { x: 0.5, y: y + 0.35, w: w1, h: 0.5, fontSize: 12, bold: true, color: HEX.white, align: "center", valign: "middle" });
      text(s, "5,415", { x: 0.5 + w1, y: y + 0.35, w: w2, h: 0.5, fontSize: 12, bold: true, color: HEX.white, align: "center", valign: "middle" });
    }
    text(s, tot, { x: 0.5 + w1 + w2 + 0.1, y: y + 0.35, w: 1.0, h: 0.5, fontSize: 14, bold: true, color: HEX.ink, valign: "middle" });
  });
  [["94A3B8", "Matcher instructions (746 tokens each call)"], [HEX.teal, "Requirement + resume evidence"]].forEach(([c, l], i) => {
    const y = 4.15 + i * 0.3;
    s.addShape(pres.shapes.RECTANGLE, { x: 0.5, y: y + 0.05, w: 0.18, h: 0.18, fill: { color: c }, line: { color: c } });
    text(s, l, { x: 0.78, y, w: 4.8, h: 0.28, fontSize: 11, color: "374151", valign: "middle" });
  });
  text(s, "Input tokens for one resume against 10 requirements", { x: 0.5, y: 1.48, w: 5.2, h: 0.3, fontSize: 11, color: HEX.muted });
  text(s, [
    { text: "12,875 vs 1,608 tokens", options: { bold: true, fontSize: 16, color: HEX.teal, breakLine: true } },
  ], { x: 6.05, y: 1.6, w: 3.45, h: 0.4 });
  s.addText(bullets([
    [{ text: "Quality: ", bold: true }, { text: "A gives each verdict its own top-5 evidence; B lets citations drift between requirements. To be measured by matcher F1." }],
    [{ text: "Latency: ", bold: true }, { text: "A makes 10 sequential calls; B makes one." }],
    [{ text: "Cost: ", bold: true }, { text: "58% of A is the same 746-token instructions sent 10 times. Prompt caching would remove most of it." }],
    [{ text: "Decision: ", bold: true }, { text: "keep A for auditable per-requirement citations; add caching." }],
  ], 12), { x: 6.05, y: 2.05, w: 3.45, h: 3.0, fontFace: FONT, valign: "top", margin: 0, isTextBox: true });
  footnote(s, "Counted with tiktoken (cl100k_base) on the strong.txt test resume and 10 seeded requirements. Quality and latency not yet measured live.");
}

// ---------- 15. Eval harness ----------
{
  const s = content("5 · Evaluation and hallucination handling", "299 backend and 28 frontend tests pass; the live-model scorecard is not built yet");
  const st = [["299", "backend tests (pytest)"], ["28", "frontend tests (vitest)"], ["2", "end-to-end smoke runs on real Postgres"]];
  st.forEach(([b, l], i) => {
    const y = 1.6 + i * 1.17;
    card(s, 0.5, y, 2.8, 1.02);
    text(s, b, { x: 0.7, y: y + 0.12, w: 1.1, h: 0.75, fontSize: 30, bold: true, color: HEX.teal, valign: "middle" });
    text(s, l, { x: 1.8, y: y + 0.12, w: 1.4, h: 0.78, fontSize: 12, color: "374151", valign: "middle" });
  });
  table(s, [
    ["Metric (PRD §11)", "Target", "Status"],
    ["Skill extraction F1", "≥ 0.80", "Not run"],
    ["Requirement matching macro-F1", "≥ 0.75", "Not run"],
    ["Groundedness of claims", "≥ 95%", "Gate tested; not scored"],
    ["Injection resumes flagged", "100%", "Fixture caught"],
    ["Copilot router accuracy", "≥ 0.90", "Not run"],
    ["Name/school swap score delta", "≤ 0.03", "Not run"],
    ["p95 intake latency", "< 30 s", "Not run"],
  ], { x: 3.6, y: 1.6, w: 5.9, colW: [2.9, 1.1, 1.9], rowH: 0.42, fontSize: 12 });
  footnote(s, "Tests use a fake model and in-memory vectors: they check logic, not model quality. The golden set and make eval are milestone M5.");
}

// ---------- 16. Test cases ----------
{
  const s = content("5 · Evaluation and hallucination handling", "Test cases cover success, ambiguity, missing evidence, attacks and one real failure");
  table(s, [
    ["Case", "Input", "Expected", "Result"],
    ["Success", "strong.txt test resume", "Cited verdicts, no flags", "Pass"],
    ["Different vocabulary", "Strong resume in other words", "No false injection flag", "Pass"],
    ["Ambiguous request", "Status change asked at pool scope", "No bulk write; warning returned", "Pass"],
    ["Missing information", "“Find similar” with no peer evidence", "No claims, no model call", "Pass"],
    ["Prompt injection", "“Ignore all previous instructions…”", "Flagged and forced to Review", "Pass"],
    ["Keyword stuffing", "Bare skills list copied from the JD", "Forced to Review", "Pass"],
    ["Live failure", "First real OpenAI intake run", "Profile completed", "Failed: insufficient_quota"],
  ], { x: 0.5, y: 1.55, w: 9, colW: [1.75, 2.75, 2.45, 2.05], rowH: 0.43, fontSize: 12, highlightRow: 7, hlFill: HEX.amberLight });
  footnote(s, "The live failure was handled as designed: status set to intake_failed, an audit event written, and the worker kept running.");
}

// ---------- 17. Hallucination handling ----------
{
  const s = content("5 · Evaluation and hallucination handling", "Unsupported claims are verified, retried, withheld or escalated, never shown as fact");
  card(s, 0.5, 1.6, 3.2, 3.45, HEX.amberLight, { line: "EBCFA8" });
  text(s, "How they arise", { x: 0.72, y: 1.75, w: 2.8, h: 0.35, fontSize: 16, bold: true, color: HEX.amber });
  s.addText(bullets([
    "Model cites a chunk it was never given",
    "Claim has no citation at all",
    "Comparison rests on one candidate",
    "Resume text tries to instruct the model",
  ], 13), { x: 0.72, y: 2.2, w: 2.85, h: 2.7, fontFace: FONT, valign: "top", margin: 0, isTextBox: true });
  const acts = [
    ["Verify", "Every chunk ID is resolved against Postgres for this job and scope"],
    ["Clarify", "A status request without a selected candidate returns a warning, not an action"],
    ["Abstain", "After 2 failed retries, unsupported claims are omitted with “couldn’t verify”"],
    ["Escalate", "Low confidence calls GitHub Deep Verify; every status change waits for HR"],
  ];
  acts.forEach(([h, d], i) => {
    const y = 1.6 + i * 0.88;
    card(s, 3.95, y, 5.55, 0.76);
    numDot(s, 4.12, y + 0.19, i + 1);
    text(s, h, { x: 4.65, y: y + 0.12, w: 1.2, h: 0.52, fontSize: 15, bold: true, valign: "middle" });
    text(s, d, { x: 5.85, y: y + 0.08, w: 3.5, h: 0.6, fontSize: 12, color: "374151", valign: "middle" });
  });
}

// ---------- 18. Infrastructure ----------
{
  const s = content("6 · Infrastructure and trade-offs", "A local Docker Compose stack on Pinecone’s free tier keeps the demo cheap");
  const layers = [
    ["Next.js web", "Applicant, HR and Tech Lead portals"],
    ["FastAPI api", "Validates, enqueues, streams SSE"],
    ["Worker", "Polls every 3 s, runs both graphs"],
    ["Postgres 16", "Records, chunks, audit, checkpoints"],
    ["Pinecone + OpenAI", "Dense/sparse indexes, us-east-1; LLM"],
  ];
  layers.forEach(([n, d], i) => {
    const y = 1.6 + i * 0.7;
    const ext = i === 4;
    card(s, 0.5, y, 3.3, 0.58, ext ? HEX.soft : HEX.white, { line: ext ? "C9D0DA" : HEX.line });
    text(s, n, { x: 0.65, y: y + 0.06, w: 3.0, h: 0.24, fontSize: 12, bold: true, color: HEX.teal });
    text(s, d, { x: 0.65, y: y + 0.3, w: 3.0, h: 0.24, fontSize: 11, color: "374151" });
  });
  table(s, [
    ["Decision", "Chosen", "Cost of the choice"],
    ["Vector store", "Pinecone + Postgres", "Dual write; needs audit and reindex"],
    ["Job runner", "Polling worker", "Slower pickup; nothing extra to run"],
    ["Embeddings", "App-side via Pinecone", "Extra call per batch; same path in tests"],
    ["Rerank", "Off by default", "Kept only if the ablation shows value"],
    ["Deployment", "Local only", "No public URL; no hosting cost"],
  ], { x: 4.1, y: 1.6, w: 5.4, colW: [1.35, 1.8, 2.25], rowH: 0.5, fontSize: 12 });
  footnote(s, "For production: managed Postgres, a queue with autoscaled workers, Langfuse tracing, real authentication and a retention policy for resume data.");
}

// ---------- 19. Demo ----------
{
  const s = content("7 · Live demo and lessons learned", "Live demo: one success path and one uncertainty path");
  const cols = [
    ["Success path", HEX.teal, HEX.white, HEX.line, [
      "Applicant uploads a strong resume to the ProCogia posting",
      "Intake runs all nine steps",
      "HR opens the checklist; each citation highlights its resume line",
      "Copilot: “Compare the top 3 on evaluation experience” takes the compare route",
    ]],
    ["Uncertainty and failure path", HEX.amber, HEX.amberLight, "EBCFA8", [
      "Injection resume is flagged and forced to Review",
      "“Does this candidate really know RAG?” has low confidence, so Deep Verify checks GitHub",
      "Grounding rejects an uncited claim, retries, then says “couldn’t verify”",
      "“Reject this candidate” pauses until HR approves",
    ]],
  ];
  cols.forEach(([h, col, fill, ln, items], i) => {
    const x = 0.5 + i * 4.6;
    card(s, x, 1.6, 4.4, 3.45, fill, { line: ln });
    text(s, h, { x: x + 0.25, y: 1.75, w: 3.9, h: 0.35, fontSize: 16, bold: true, color: col });
    items.forEach((t, j) => {
      const y = 2.25 + j * 0.68;
      numDot(s, x + 0.25, y, j + 1, col);
      text(s, t, { x: x + 0.78, y: y - 0.04, w: 3.45, h: 0.62, fontSize: 12, valign: "top" });
    });
  });
  footnote(s, "A live-model demo needs OpenAI credits; without them, the smoke runs exercise the same graphs with a fake model.");
}

// ---------- 20. Lessons ----------
{
  const s = content("7 · Live demo and lessons learned", "Hard invariants held up; the live model path should have been tested on day one");
  const cols = [
    ["What worked", HEX.teal, [
      "Citations as a hard rule: uncited claims never reach the UI",
      "Fake model and in-memory vectors made 299 tests run in 2 s",
      "Postgres first, so Pinecone can always be rebuilt",
    ]],
    ["What didn’t", HEX.amber, [
      "The live OpenAI run failed on quota, found late",
      "Disk exhaustion corrupted the Docker Postgres volume",
      "Parallel coding agents made unrequested commits and overwrote work",
    ]],
    ["What I learned", HEX.ink, [
      "Run one real end-to-end call before building on top of it",
      "Write the invariants down before the code",
      "Give parallel agents separate files and fix shared contracts first",
    ]],
  ];
  cols.forEach(([h, col, items], i) => {
    const x = 0.5 + i * 3.05;
    card(s, x, 1.6, 2.85, 3.45);
    text(s, h, { x: x + 0.2, y: 1.75, w: 2.5, h: 0.35, fontSize: 16, bold: true, color: col });
    s.addText(bullets(items, 13), { x: x + 0.2, y: 2.2, w: 2.5, h: 2.75, fontFace: FONT, valign: "top", margin: 0, isTextBox: true });
  });
}

// ---------- 21. Limitations and next steps ----------
{
  const s = content("8 · Limitations and next steps", "Live evaluation comes first, then production hardening");
  card(s, 0.5, 1.6, 4.0, 3.45, HEX.amberLight, { line: "EBCFA8" });
  text(s, "Key risks", { x: 0.72, y: 1.75, w: 3.6, h: 0.35, fontSize: 16, bold: true, color: HEX.amber });
  s.addText(bullets([
    "No live-model quality evidence yet",
    "Synthetic resumes and a 170-skill taxonomy",
    "Fairness (name and school swaps) untested",
    "Demo role switcher, not real authentication",
    "Resume text is sent to Pinecone and OpenAI",
  ], 13), { x: 0.72, y: 2.2, w: 3.6, h: 2.75, fontFace: FONT, valign: "top", margin: 0, isTextBox: true });
  const next = [
    "Restore credits; label 30–50 resumes and set the eval baseline",
    "Build the Tech Lead portal: rubric, comments, invite",
    "Add Langfuse traces and cost per resume",
    "Load full O*NET and ESCO; add licensed real resumes",
    "Prompt caching and the rerank ablation",
    "Real auth, queue-based workers, data retention",
  ];
  text(s, "Next steps, in order", { x: 4.8, y: 1.62, w: 4.7, h: 0.35, fontSize: 16, bold: true, color: HEX.teal });
  next.forEach((t, i) => {
    const y = 2.08 + i * 0.5;
    numDot(s, 4.8, y, i + 1);
    text(s, t, { x: 5.3, y: y + 0.02, w: 4.2, h: 0.4, fontSize: 13, valign: "middle" });
  });
}

// ---------- 22. Close ----------
{
  const s = pres.addSlide({ masterName: "DARK" });
  text(s, "Questions", { x: 0.7, y: 1.8, w: 8.6, h: 0.9, fontSize: 44, bold: true, color: HEX.white, align: "center" });
  text(s, "The AI recommends, with citations. People decide.", { x: 0.7, y: 2.8, w: 8.6, h: 0.5, fontSize: 20, color: "D6DCE4", align: "center" });
}

(async () => {
  await pres.writeFile({ fileName: OUT });
  await applyTheme(OUT, THEME);
  console.log("wrote", OUT);
})();
