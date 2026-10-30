# Question Workflow - reading material -> reviewed 5-question group

Paste reading material, get **2 theory MCQ + 2 True/False + 1 code-analysis** in a tagged format, then a
reviewer judges, edits, approves/rejects each question before export.

**Stack:** React (Vite) + Python FastAPI + Claude (Anthropic) **or Gemini (Google)** - switchable via `.env`. No DB (stateless).

## Setup (2 terminals)
```bash
# 1) Backend  (Python 3.10+)
cd backend
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env            # put GEMINI_API_KEY=... or ANTHROPIC_API_KEY=... (optional); LLM_PROVIDER=gemini|anthropic|auto
uvicorn app:app --port 8000 --reload

# 2) Frontend (Node 18+)
cd frontend
npm install
npm run dev                     # open http://localhost:5173
```
No API key? It still runs in **DEMO mode** (heuristic questions built from the material's own sentences) so the
whole workflow is testable offline. Real quality needs the key. Click **Load sample** to try quickly.

## The key rule: "a question that tests something not taught = failed"
Prompting alone cannot guarantee this, so it is enforced in code:
1. The model must return an **`evidence`** field: a verbatim sentence from the material that proves the answer.
2. Backend checks `evidence` is a real substring of the material (whitespace/case-normalised). The **code** of the
   code-analysis question must also be a verbatim snippet from the material.
3. Failing questions are **auto-retried (max 2)** with the failure reason fed back to the model.
4. Still failing -> shown to the reviewer in red with the reason; **Approve is disabled** and **export is blocked**
   (UI *and* server return 422). Edits are re-validated live (debounced call to `/api/validate`).

## Tagged format
No sample was provided, so I assumed an XML-style schema (`<question_group><question type=...><text/><options/>
<explanation/><source_evidence/>`). It lives in one function, `to_tagged()` in `backend/app.py` - change it to match any spec.

## API
`GET /api/health` `GET /api/sample` `POST /api/generate` `POST /api/regenerate` `POST /api/validate` `POST /api/export`

## Decisions & trade-offs
| Decision | Why | Trade-off |
|---|---|---|
| Deterministic quote check instead of "LLM judges LLM" | Cheap, explainable, cannot be talked around | Proves the *fact is in the text*, not that the question is well-written or the distractors good - that is why the human review step exists |
| Strict verbatim evidence | Hard, testable definition of "taught" | Can reject a good question whose answer needs two sentences combined or a paraphrase; reviewer can edit evidence |
| One-shot group generation + per-question regeneration | 1 call per group = cheaper, consistent; fixes are local | Questions in a group may overlap slightly |
| FastAPI + Pydantic | Typed validation of model JSON, tiny code | Model output must still be defended against malformed JSON (handled with retry) |
| Stateless, no DB / auth | Opens and runs in seconds | Reviewer work is lost on refresh; no history/audit trail |
| DEMO mode | Evaluators can run it with no key | Demo questions are low quality - clearly badged |

## What I'd do next
Persist drafts + reviewer decisions (SQLite) to build a quality dataset, semantic (not only verbatim) grounding with
embeddings, LLM-as-judge for distractor quality, difficulty/Bloom tagging, multi-chapter input chunking, tests/CI.
