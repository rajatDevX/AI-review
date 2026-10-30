import { useEffect, useRef, useState } from "react";
import { api } from "./api.js";

const LABEL = { mcq: "Theory MCQ", tf: "True / False", code: "Code analysis" };

export default function App() {
  const [material, setMaterial] = useState("");
  const [mode, setMode] = useState(null);
  const [provider, setProvider] = useState(null);
  const [qs, setQs] = useState([]);           // each: question + check + verdict(pending|approved|rejected)
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [tagged, setTagged] = useState("");

  useEffect(() => { api.health().then((h) => { setMode(h.mode); setProvider(h.provider); }).catch(() => setErr("Backend not reachable on :8000")); }, []);

  const run = async (fn) => { setBusy(true); setErr(""); try { await fn(); } catch (e) { setErr(e.message); } finally { setBusy(false); } };

  const generate = () => run(async () => {
    const r = await api.generate(material);
    setMode(r.mode); setTagged("");
    setQs(r.questions.map((q) => ({ ...q, verdict: "pending" })));
  });
  const loadSample = () => run(async () => setMaterial((await api.sample()).material));
  const regen = (q) => run(async () => {
    const n = await api.regenerate(material, q.type, q.id);
    setQs((l) => l.map((x) => (x.id === q.id ? { ...n, verdict: "pending" } : x))); setTagged("");
  });
  const update = (id, patch) => { setTagged(""); setQs((l) => l.map((x) => (x.id === id ? { ...x, ...patch, verdict: patch.verdict || "pending" } : x))); };

  const approved = qs.filter((q) => q.verdict === "approved").length;
  const allOk = qs.length === 5 && qs.every((q) => q.verdict === "approved" && q.check?.ok);
  const doExport = () => run(async () => {
    const clean = qs.map(({ check, verdict, ...q }) => q);
    setTagged((await api.exportTagged(material, clean)).tagged);
  });

  return (
    <div className="page">
      <header>
        <h1>Question Workflow</h1>
        <span className={"pill " + (mode === "ai" ? "ok" : "warn")}>{mode === "ai" ? "AI mode" + (provider ? " · " + provider : "") : mode === "demo" ? "DEMO mode (no API key)" : "…"}</span>
      </header>
      <ol className="steps"><li className={qs.length ? "done" : "on"}>1 Paste material</li><li className={qs.length ? "on" : ""}>2 Review &amp; fix each question</li><li className={allOk ? "on" : ""}>3 Export tagged group</li></ol>
      {err && <div className="err">{err}</div>}

      <section className="card">
        <div className="row"><h2>Reading material</h2><button className="ghost" onClick={loadSample} disabled={busy}>Load sample</button></div>
        <textarea rows={9} value={material} onChange={(e) => setMaterial(e.target.value)} placeholder="Paste reading material (markdown / text) here…" />
        <button className="primary" onClick={generate} disabled={busy || material.trim().length < 50}>{busy ? "Working…" : qs.length ? "Regenerate whole group" : "Generate 5 questions"}</button>
      </section>

      {qs.map((q) => <QCard key={q.id} q={q} material={material} busy={busy} onChange={(p) => update(q.id, p)} onRegen={() => regen(q)} />)}

      {qs.length === 5 && (
        <section className="card">
          <div className="row">
            <strong>{approved}/5 approved</strong>
            <button className="primary" disabled={!allOk || busy} onClick={doExport}>Export tagged output</button>
          </div>
          {!allOk && <p className="muted">Export unlocks when all 5 are approved and every question passes the grounding check.</p>}
          {tagged && (<><pre className="out">{tagged}</pre>
            <button className="ghost" onClick={() => navigator.clipboard.writeText(tagged)}>Copy</button></>)}
        </section>
      )}
    </div>
  );
}

function QCard({ q, material, busy, onChange, onRegen }) {
  const t = useRef();
  // live re-validation whenever the reviewer edits (debounced)
  useEffect(() => {
    clearTimeout(t.current);
    t.current = setTimeout(async () => {
      try { const { check, verdict, ...bare } = q; const c = await api.validate(material, bare); onChange2(c); } catch {}
    }, 400);
    return () => clearTimeout(t.current);
    // eslint-disable-next-line
  }, [q.text, q.code, q.evidence, JSON.stringify(q.options)]);
  const onChange2 = (c) => onChange({ check: c, verdict: q.verdict });

  const failed = !q.check?.ok;
  const setOpt = (i, patch) => onChange({ options: q.options.map((o, k) => (k === i ? { ...o, ...patch } : patch.correct ? { ...o, correct: false } : o)) });

  return (
    <section className={"card q " + q.verdict}>
      <div className="row"><h3>Q{q.id} · {LABEL[q.type]}</h3>
        <span className={"pill " + (failed ? "bad" : "ok")}>{failed ? "Not grounded / invalid" : "Grounded ✓"}</span></div>

      <label>Question</label>
      <textarea rows={2} value={q.text} onChange={(e) => onChange({ text: e.target.value })} />

      {q.type === "code" && (<><label>Code (must come from the material)</label>
        <textarea className="mono" rows={6} value={q.code} onChange={(e) => onChange({ code: e.target.value })} /></>)}

      <label>Options (select the correct one)</label>
      {q.options.map((o, i) => (
        <div className="opt" key={i}>
          <input type="radio" checked={o.correct} onChange={() => setOpt(i, { correct: true })} />
          {q.type === "tf" ? <span>{o.text}</span> : <input value={o.text} onChange={(e) => setOpt(i, { text: e.target.value })} />}
        </div>))}

      <label>Evidence — exact sentence from the material</label>
      <textarea rows={2} value={q.evidence} onChange={(e) => onChange({ evidence: e.target.value })} />
      <label>Explanation</label>
      <textarea rows={2} value={q.explanation} onChange={(e) => onChange({ explanation: e.target.value })} />

      {failed && q.check?.issues?.length > 0 && <ul className="issues">{q.check.issues.map((s, i) => <li key={i}>{s}</li>)}</ul>}

      <div className="row actions">
        <button className="primary" disabled={failed} title={failed ? "Fix the issues first" : ""} onClick={() => onChange({ verdict: "approved" })}>Approve</button>
        <button className="danger" onClick={() => onChange({ verdict: "rejected" })}>Reject</button>
        <button className="ghost" onClick={onRegen} disabled={busy}>Regenerate this</button>
        <span className="muted">{q.verdict}</span>
      </div>
    </section>
  );
}
