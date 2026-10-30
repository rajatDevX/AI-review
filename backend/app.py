"""AI Question Workflow - backend (FastAPI).

Pipeline:  material -> LLM draft -> deterministic grounding check -> auto-retry
           -> reviewer edits (re-validated live) -> tagged export (gated).
"""
import json, os, re, random
from typing import List, Optional
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from xml.sax.saxutils import escape

load_dotenv()
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL") or os.getenv("MODEL", "claude-sonnet-4-6")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# LLM_PROVIDER: "auto" (default) | "anthropic" | "gemini"
#   auto -> Anthropic if its key is set, else Gemini if its key is set, else DEMO mode.
_pref = os.getenv("LLM_PROVIDER", "auto").strip().lower()
if _pref == "gemini" and GEMINI_API_KEY:
    PROVIDER = "gemini"
elif _pref == "anthropic" and ANTHROPIC_API_KEY:
    PROVIDER = "anthropic"
elif _pref == "auto" and ANTHROPIC_API_KEY:
    PROVIDER = "anthropic"
elif _pref == "auto" and GEMINI_API_KEY:
    PROVIDER = "gemini"
else:
    PROVIDER = ""                      # no usable key -> DEMO mode
API_KEY = PROVIDER                     # truthy => AI mode (kept so the rest of the code is unchanged)
MODEL = GEMINI_MODEL if PROVIDER == "gemini" else ANTHROPIC_MODEL
PLAN = ["mcq", "mcq", "tf", "tf", "code"]          # the required 2/2/1 group
MAX_RETRIES = 2

app = FastAPI(title="Question Workflow API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ---------- models ----------
class Option(BaseModel):
    text: str
    correct: bool = False

class Question(BaseModel):
    id: int
    type: str                      # mcq | tf | code
    text: str
    code: Optional[str] = ""
    options: List[Option]
    explanation: str = ""
    evidence: str = ""             # verbatim sentence(s) from the material that prove the answer

class GenerateReq(BaseModel):
    material: str

class RegenReq(BaseModel):
    material: str
    type: str
    id: int

class ValidateReq(BaseModel):
    material: str
    question: Question

class ExportReq(BaseModel):
    material: str
    questions: List[Question]


# ---------- grounding / structure checks (deterministic, no AI) ----------
def norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip().lower()

def check(material: str, q: Question) -> dict:
    """Returns {ok, issues[]}. A question that fails is 'failed' and cannot be exported."""
    issues, m = [], norm(material)
    if not q.text.strip():
        issues.append("Question text is empty.")
    correct = [o for o in q.options if o.correct]
    if q.type == "mcq" and len(q.options) != 4:
        issues.append("MCQ needs exactly 4 options.")
    if q.type == "tf" and [norm(o.text) for o in q.options] != ["true", "false"]:
        issues.append("True/False must have options True and False.")
    if q.type == "code" and len(q.options) != 4:
        issues.append("Code question needs exactly 4 options.")
    if len(correct) != 1:
        issues.append("Exactly one option must be marked correct.")
    if any(not o.text.strip() for o in q.options):
        issues.append("An option is empty.")
    if q.type != "tf" and len({norm(o.text) for o in q.options}) != len(q.options):
        issues.append("Duplicate options.")
    # --- the core rule: must be taught by the material ---
    if len(norm(q.evidence)) < 15:
        issues.append("Missing evidence: quote the sentence from the material that proves the answer.")
    elif norm(q.evidence) not in m:
        issues.append("GROUNDING FAIL: evidence is not a verbatim quote from the material.")
    if q.type == "code":
        if not q.code.strip():
            issues.append("Code snippet is empty.")
        elif norm(q.code) not in m:
            issues.append("GROUNDING FAIL: code is not from the material (it must be a snippet the material teaches).")
    return {"ok": not issues, "issues": issues}


# ---------- LLM generation ----------
SYSTEM = """You write assessment questions for beginner learners from reading material.
HARD RULES:
1. Test ONLY what the material explicitly teaches. No outside knowledge, no new facts.
2. Every question needs "evidence": an EXACT, verbatim, copy-pasted sentence from the material that proves the correct answer.
3. For the code-analysis question, "code" must be copied verbatim from a code block in the material; ask the learner to predict output/behaviour using only facts taught in the material.
4. MCQ: 4 options, exactly 1 correct, plausible distractors. TF: options are exactly "True" and "False". Code: 4 options, exactly 1 correct.
5. Return ONLY JSON, no markdown fences."""

SHAPE = '{"type":"mcq|tf|code","text":"...","code":"" ,"options":[{"text":"...","correct":false}],"explanation":"...","evidence":"verbatim sentence"}'

def call_anthropic(prompt: str) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    r = client.messages.create(model=ANTHROPIC_MODEL, max_tokens=3000, system=SYSTEM,
                               messages=[{"role": "user", "content": prompt}])
    return "".join(b.text for b in r.content if b.type == "text")

def call_gemini(prompt: str) -> str:
    """Gemini via the REST API (httpx) - no extra SDK needed."""
    import httpx
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
    body = {
        "systemInstruction": {"parts": [{"text": SYSTEM}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": 8192, "temperature": 0.4,
                             "responseMimeType": "application/json"},
    }
    r = httpx.post(url, json=body, headers={"x-goog-api-key": GEMINI_API_KEY}, timeout=90)
    if r.status_code != 200:
        raise RuntimeError(f"Gemini API {r.status_code}: {r.text[:300]}")
    data = r.json()
    cands = data.get("candidates") or []
    if not cands:
        raise RuntimeError(f"Gemini returned no candidates: {data.get('promptFeedback', data)}")
    parts = (cands[0].get("content") or {}).get("parts") or []
    return "".join(p.get("text", "") for p in parts)

def call_llm(prompt: str) -> str:
    return call_gemini(prompt) if PROVIDER == "gemini" else call_anthropic(prompt)

def parse_json(txt: str):
    txt = re.sub(r"^```(?:json)?|```$", "", txt.strip(), flags=re.M).strip()
    return json.loads(txt)

def llm_group(material: str) -> List[dict]:
    p = (f"READING MATERIAL:\n<<<\n{material}\n>>>\n\nWrite exactly 5 questions in this order: "
         f"2 mcq, 2 tf, 1 code. Return a JSON array of 5 objects shaped like {SHAPE}")
    return parse_json(call_llm(p))

def llm_one(material: str, qtype: str, avoid: str, issues: List[str]) -> dict:
    p = (f"READING MATERIAL:\n<<<\n{material}\n>>>\n\nWrite ONE new '{qtype}' question shaped like {SHAPE}. "
         f"Do not repeat this question: {avoid!r}. Previous attempt failed because: {issues}")
    return parse_json(call_llm(p))


# ---------- DEMO mode (no API key): heuristic, so the app runs out of the box ----------
def demo_one(material: str, qtype: str, i: int, avoid: str = "") -> dict:
    prose = re.sub(r"```.*?```", "", material, flags=re.S)
    sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", prose.replace("\n", " ")) if len(s.strip()) > 30 and not s.startswith("#")]
    pool = [s for s in sents if s != avoid] or sents
    rnd = random.Random(i * 7 + len(avoid))
    s = rnd.choice(pool)
    def negate(x):
        return x.replace(" is ", " is not ", 1) if " is " in x else x.replace(" are ", " are not ", 1) if " are " in x else "It is false that " + x[0].lower() + x[1:]
    if qtype == "tf":
        make_false = i % 2 == 1
        stmt = negate(s) if make_false else s
        return {"type": "tf", "text": f"True or False: {stmt}", "code": "", "evidence": s,
                "options": [{"text": "True", "correct": not make_false}, {"text": "False", "correct": make_false}],
                "explanation": "Demo mode. Original sentence: " + s}
    if qtype == "mcq":
        others = rnd.sample([x for x in pool if x != s] or pool, k=min(3, max(1, len(pool) - 1)))
        opts = [{"text": s, "correct": True}] + [{"text": negate(o), "correct": False} for o in others]
        while len(opts) < 4: opts.append({"text": negate(s) + " (variant)", "correct": False})
        rnd.shuffle(opts)
        return {"type": "mcq", "text": "Which statement is supported by the reading material?", "code": "",
                "options": opts, "evidence": s, "explanation": "Demo mode. Correct option is the original sentence."}
    blocks = re.findall(r"```\w*\n(.*?)```", material, flags=re.S)
    code = (blocks[i % len(blocks)] if blocks else "").strip()
    first = (code.splitlines() or [""])[0]
    return {"type": "code", "text": "Read the code. What is the main purpose of the snippet?", "code": code, "evidence": s,
            "options": [{"text": "It demonstrates: " + s[:90], "correct": True},
                        {"text": "It sorts the data in descending order", "correct": False},
                        {"text": "It reads a file from disk", "correct": False},
                        {"text": f"It only defines `{first[:30]}` and does nothing else", "correct": False}],
            "explanation": "Demo mode placeholder. Use an API key for real code-analysis questions."}


def build_one(material: str, qtype: str, qid: int, avoid: str = "", draft: Optional[dict] = None) -> Question:
    """Generate -> check -> retry with failure feedback. Returns the last attempt either way
    (flagged by the checker if still failing, so the reviewer sees why)."""
    issues: List[str] = []
    q = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            if draft and attempt == 0:
                d = dict(draft)
            elif API_KEY:
                d = llm_one(material, qtype, avoid, issues)
            else:
                d = demo_one(material, qtype, qid + attempt, avoid)
        except Exception as e:  # noqa
            raise HTTPException(502, f"Model call failed: {e}")
        try:
            q = Question(id=qid, type=qtype, text=str(d.get("text", "")), code=str(d.get("code") or ""),
                         options=[Option(**o) for o in d.get("options", [])],
                         explanation=str(d.get("explanation", "")), evidence=str(d.get("evidence", "")))
        except Exception:
            issues = ["Malformed JSON structure."]
            continue
        res = check(material, q)
        if res["ok"]:
            break
        issues = res["issues"]
    if q is None:
        q = Question(id=qid, type=qtype, text="(generation failed - write this question manually)", options=[])
    return q


# ---------- routes ----------
@app.get("/api/health")
def health():
    return {"ok": True, "mode": "ai" if API_KEY else "demo", "provider": PROVIDER or None, "model": MODEL if API_KEY else None}

@app.get("/api/sample")
def sample():
    with open(os.path.join(os.path.dirname(__file__), "sample_material.md"), encoding="utf-8") as f:
        return {"material": f.read()}

@app.post("/api/generate")
def generate(req: GenerateReq):
    if len(req.material.strip()) < 200:
        raise HTTPException(400, "Reading material is too short to build 5 grounded questions (min ~200 chars).")
    drafts = []
    if API_KEY:
        try:
            drafts = llm_group(req.material)
        except Exception as e:
            raise HTTPException(502, f"Model call failed: {e}")
    out = []
    for i, t in enumerate(PLAN):
        d = drafts[i] if i < len(drafts) and isinstance(drafts[i], dict) else None
        out.append(build_one(req.material, t, i + 1, draft=d))
    return {"mode": "ai" if API_KEY else "demo", "questions": [with_check(req.material, q) for q in out]}

@app.post("/api/regenerate")
def regenerate(req: RegenReq):
    return with_check(req.material, build_one(req.material, req.type, req.id, avoid=f"{random.random()}"))

@app.post("/api/validate")
def validate(req: ValidateReq):
    return check(req.material, req.question)

@app.post("/api/export")
def export(req: ExportReq):
    if len(req.questions) != 5 or [q.type for q in req.questions] != PLAN:
        raise HTTPException(422, "Group must be exactly: 2 mcq, 2 tf, 1 code (in that order).")
    bad = {q.id: check(req.material, q)["issues"] for q in req.questions if not check(req.material, q)["ok"]}
    if bad:
        raise HTTPException(422, {"message": "Some questions fail validation.", "failed": bad})
    return {"tagged": to_tagged(req.questions)}

def with_check(material, q: Question):
    return {**q.model_dump(), "check": check(material, q)}

def to_tagged(qs: List[Question]) -> str:
    """Tagged output format (assumed schema - see README). Swap this one function to match a different spec."""
    lines = ['<question_group count="5">']
    for q in qs:
        lines.append(f'  <question id="{q.id}" type="{q.type}">')
        lines.append(f"    <text>{escape(q.text)}</text>")
        if q.code.strip():
            lines.append(f"    <code><![CDATA[\n{q.code.strip()}\n    ]]></code>")
        lines.append("    <options>")
        for n, o in enumerate(q.options):
            lines.append(f'      <option key="{chr(65 + n)}" correct="{str(o.correct).lower()}">{escape(o.text)}</option>')
        lines.append("    </options>")
        lines.append(f"    <explanation>{escape(q.explanation)}</explanation>")
        lines.append(f"    <source_evidence>{escape(q.evidence)}</source_evidence>")
        lines.append("  </question>")
    lines.append("</question_group>")
    return "\n".join(lines)
