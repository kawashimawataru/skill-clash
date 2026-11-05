#!/usr/bin/env python3
"""skill-clash: find instruction conflicts, trigger overlap and token cost between
Claude Code skills before loading several at once, and suggest where each skill belongs.
Stdlib only. Exit codes: 0 no problem, 1 clash or over budget, 2 error."""
import argparse, json, math, os, random, re, sys
from itertools import combinations
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
USER_DIR = "~/.claude/skills"


def default_dirs():
    """The skills Claude actually sees: ~/.claude/skills plus the skills/ folder of every
    enabled plugin. ~/.agents/skills is left out on purpose (it keeps unlinked old skills).
    shortcut: plugins that declare a custom skills path in plugin.json are missed; read it when one turns up."""
    home = Path(os.path.expanduser("~/.claude"))
    out = [USER_DIR]
    try:
        enabled = {k for k, v in json.loads((home / "settings.json").read_text(encoding="utf-8")).get("enabledPlugins", {}).items() if v}
        installed = json.loads((home / "plugins" / "installed_plugins.json").read_text(encoding="utf-8")).get("plugins", {})
    except (OSError, ValueError):
        return out
    for key, entries in installed.items():
        if key in enabled:
            out += [str(Path(e["installPath"]) / "skills") for e in entries[-1:] if e.get("installPath")]
    return out


def resolve_dirs(a):
    """--dirs adds to the defaults; --no-defaults drops them."""
    extra = getattr(a, "dirs", None) or []
    return (extra if getattr(a, "no_defaults", False) else default_dirs() + extra) or default_dirs()
CJK = re.compile(r"[぀-ヿ㐀-鿿ｦ-ﾟ]")
CJK_RUN = re.compile(r"[぀-ヿ㐀-鿿ｦ-ﾟ]+")
STOP = set("""a an and or the of to in on for with by from as at is are be this that these those it its
into your you their our any all when use used uses using user users skill skills mentions mention trigger
also not but than then such via like can will should must what which who how about over under each
covers cover see other more most very just only own make makes etc e.g i.e asks ask want wants""".split())
REVIEW_HINT = re.compile(r"review|audit|critique|check|evaluat|inspect|lint|detect|点検|見直|レビュー|監査", re.I)
BUILD_HINT = re.compile(r"build|create|generat|make|craft|author|implement|作る|作成", re.I)


def is_review(desc):
    """Review skill if a review verb shows up before any build verb."""
    r, b = REVIEW_HINT.search(desc), BUILD_HINT.search(desc)
    return bool(r) and (not b or r.start() < b.start())
TRIGGER = re.compile(r"\buse (this |it )?(when|for|whenever|if)\b|\bbefore (every|any|calling)\b|\bwhenever\b|\bwhen (the user|you|asked)|\btrigger|\binvoke when|とき|場合|際に", re.I)
USE_FIRST = re.compile(r"^\s*(use (this|when|for|whenever)|when |trigger|～?.{0,40}(とき|場合)に?使)", re.I)


# ---------- loading ----------
def parse_frontmatter(text):
    lines = text.split("\n")
    meta, body_start = {}, 0
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                body_start = i + 1
                break
        key = None
        for ln in lines[1:body_start - 1]:
            m = re.match(r"^([A-Za-z_-]+):\s*(.*)$", ln)
            if m:
                key, val = m.group(1), m.group(2).strip()
                meta[key] = "" if val in (">", "|", ">-", "|-") else val
            elif key and ln.startswith((" ", "\t")):
                meta[key] = (meta[key] + " " + ln.strip()).strip()
        for k, v in meta.items():
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                meta[k] = v[1:-1]
    return meta, body_start


def count_words(text):
    cjk = len(CJK.findall(text))
    latin = len(CJK.sub(" ", text).split())
    return latin + cjk // 2


def plugin_of(root):
    """'frontend-design' for .../plugins/cache/<market>/frontend-design/<version>/skills."""
    return root.parent.parent.name if root.name == "skills" and "plugins" in root.parts else None


def load_skills(dirs=None):
    dirs = dirs or default_dirs()
    seen, skills = set(), []
    for d in dirs:
        root = Path(os.path.expanduser(d))
        if not root.is_dir():
            continue
        for f in sorted(root.glob("*/SKILL.md")):
            real = f.resolve()
            if real in seen or real.parent == HERE:
                continue
            seen.add(real)
            text = real.read_text(encoding="utf-8", errors="replace")
            if text in seen:  # identical copy (not a symlink) in another root
                continue
            seen.add(text)
            s = read_skill(real, text, f.parent.name)
            if plugin_of(root):  # Claude lists plugin skills as plugin:skill
                s["name"] = f"{plugin_of(root)}:{s['name']}"
            if any(x["name"] == s["name"] for x in skills):  # same name, different file
                s["name"] = f"{s['name']}@{root.parent.name}/{root.name}"
                s["dup"] = True
            skills.append(s)
    return skills


def read_skill(path, text=None, dirname=None):
    text = text if text is not None else Path(path).read_text(encoding="utf-8", errors="replace")
    meta, body_start = parse_frontmatter(text)
    lines = text.split("\n")
    words = count_words("\n".join(lines[body_start:]))
    dirname = dirname or Path(path).parent.name
    return {"name": meta.get("name") or dirname, "dir": dirname, "path": str(path),
            "description": meta.get("description", ""), "words": words, "tokens": round(words * 1.3),
            "lines": lines, "body_start": body_start}


class Fail(Exception):
    """A usage or input error: printed without a traceback, exit code 2."""


def find(skills, name):
    for s in skills:
        if name in (s["name"], s["dir"]):
            return s
    raise Fail(f"unknown skill: {name} (run `scan` to list names)")


# ---------- tokens / overlap ----------
def tokens(text):
    out = set()
    for w in re.findall(r"[a-z][a-z0-9-]+", CJK.sub(" ", text.lower())):
        w = w.strip("-")
        if len(w) < 3 or w in STOP:
            continue
        if len(w) > 4 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        out.add(w)
    for run in CJK_RUN.findall(text):  # Japanese: character bigrams
        out.update(run[i:i + 2] for i in range(len(run) - 1))
    return out


def jaccard(a, b):
    return len(a & b) / len(a | b) if a | b else 0.0


def overlap(skills, threshold=0.25, top=20):
    toks = {s["name"]: tokens(s["description"]) for s in skills}
    pairs = []
    for a, b in combinations(skills, 2):
        j = jaccard(toks[a["name"]], toks[b["name"]])
        if j >= threshold:
            shared = sorted(toks[a["name"]] & toks[b["name"]])
            pairs.append((round(j, 3), a["name"], b["name"], shared))
    pairs.sort(key=lambda p: -p[0])
    return pairs[:top]


# ---------- conflict ----------
HIRA2 = re.compile(r"^[぀-ゟ]")  # bigrams that open with a particle (「のあ」「を作」) match everything


def load_aliases(path=None):
    lex = json.loads(Path(path or HERE / "lexicon.json").read_text(encoding="utf-8"))
    return lex.get("ja_en", [])


def task_tokens(task, aliases):
    """Request words; Japanese words also bring the English words from lexicon.json ja_en (same as the page)."""
    extra = " ".join(en for rx, en in aliases if re.search(rx, task, re.I))
    return {w for w in tokens(task + " " + extra) if not HIRA2.match(w)}


def load_lexicon(path=None):
    lex = json.loads(Path(path or HERE / "lexicon.json").read_text(encoding="utf-8"))
    comp = lambda pats: [re.compile(p, re.I) for p in pats]
    axes = {k: {"include": comp(v.get("include") or v.get("terms", [])), "exclude": comp(v.get("exclude", []))}
            for k, v in lex["axes"].items()}
    return axes, comp(lex["negative"]), comp(lex["positive"])


SENT_SPLIT = re.compile(r"(?<=[.!?])(?:\*\*|[\"')`])?\s+|(?<=[。！？])")  # ".** Next", ".) Next" too
LIST_ITEM = re.compile(r"^\s*(([-*+]|\d+[.)])\s+|\|)")  # list items and table rows
HEADING = re.compile(r"^(#{1,6})\s+(.*)")
BOLD_LABEL = re.compile(r"^\*\*([^*]{1,60}?):?\*\*(:|\s*$)")  # "**Avoid:**" or a bold-only line, not a list item
STRONG = re.compile(r"\bnever\b|\bban(s|ned)?\b|\bforbid\w*|禁止", re.I)
CTX_NEG = re.compile(r"\bavoid\w*|\bnever\b|\bdon'?t\b|anti-?patterns?|\bslop\b|\bforbidden\b|\bbanned\b|避け|禁止|しない|\bNG\b", re.I)
CTX_POS = re.compile(r"\brecommend\w*|\buse\b|\bprefer\w*|\bdo\b|\bgood\b|勧め|使う", re.I)
KEBAB = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)+", re.I)
SYMBOL = {"recommends": "✓", "avoids": "✗", "mixed": "~"}


def section_ctx(label):
    """-1 for an avoid section, +1 for a recommend section, 0 when neither or both."""
    n, p = bool(CTX_NEG.search(label)), bool(CTX_POS.search(label))
    return -1 if n and not p else +1 if p and not n else 0


def polarity_spans(sentence, neg, pos):
    """Return [(start, end, +1/-1)]. Negatives first; their span masks positives."""
    spans, masked = [], sentence
    for rx in neg:
        for m in rx.finditer(sentence):
            spans.append((m.start(), m.end(), -1))
            masked = masked[:m.start()] + " " * (m.end() - m.start()) + masked[m.end():]
    neg_ends = [e for _, e, _ in spans]
    for rx in pos:
        for m in rx.finditer(masked):
            # "never use", "don't ever use": a cue right after a negation is negated
            if not any(0 <= m.start() - e <= 8 for e in neg_ends):
                spans.append((m.start(), m.end(), +1))
    return spans


def nearest(spans, at):
    return min(spans, key=lambda s: min(abs(s[0] - at), abs(s[1] - at)))[2] if spans else 0


LEAD = re.compile(r"^[\s>*_`#|-]*(\d+[.)]\s*)?")
VERDICT = re.compile(r"ai-generated|\bgeneric\b|\bslop\b|\bclich|\btemplated\b|signals? ai|ありがち|AIっぽ|既定の型", re.I)
NEAR = 60  # chars; a cue farther than this from the term is about something else
CLAUSE = re.compile(r"[,;:()\[\]—–、；：（）]|\s-\s")


def resolve(sentence, spans, at, ctx):
    """Direction of the cue that governs position `at`:
    1. a negation opening the sentence ("DO NOT use X", "Never ...") wins;
    2. else the nearest cue in the same clause (split on , ; : — parentheses);
       ("...so the two rules never fight" is too far from "Tracking" to govern it);
    3. else the section context (heading, bold label, '...:' lead-in);
    4. else the sentence's first cue before the term (a leading verb governs a comma list)."""
    if spans:
        head = LEAD.match(sentence).end()
        first = min(spans, key=lambda s: s[0])
        if first[2] < 0 and first[0] <= head + 1:
            return -1
        lo = max([m.end() for m in CLAUSE.finditer(sentence, 0, at)] or [0])
        m = CLAUSE.search(sentence, at)
        hi = m.start() if m else len(sentence)
        inside = [s for s in spans if lo <= s[0] < hi and min(abs(s[0] - at), abs(s[1] - at)) <= NEAR
                  and not (s[0] > at and sentence[s[0]:s[1]].lower() == "no")]  # "X with no <img>": "no" governs what follows
        if inside:
            return nearest(inside, at)
    lead = [s for s in spans if s[0] < at]  # only a cue before the term can govern it
    if ctx or lead:
        return ctx or min(lead)[2]
    # "same card grid, same metric boxes signals AI-generated": a verdict judges the whole sentence
    return -1 if spans and all(s[2] < 0 for s in spans) and VERDICT.search(sentence) else 0


def excerpt(sentence, at, width=110):
    s = sentence.strip()
    if len(s) <= width:
        return s
    i = max(0, min(at - width // 3, len(s) - width))
    return ("…" if i else "") + s[i:i + width].strip() + ("…" if i + width < len(s) else "")


def is_name(sent, m):
    """The hit is part of a kebab-case identifier (`rainbow-gradient`) in backticks or in a
    comma list of such identifiers (a theme or file name catalogue), not a design instruction."""
    k = next((k for k in KEBAB.finditer(sent) if k.start() <= m.start() and m.end() <= k.end()), None)
    if not k or (k.start(), k.end()) == m.span():
        return False
    in_ticks = sent[:k.start()].endswith("`") and sent[k.end():].startswith("`")
    return in_ticks or len(KEBAB.findall(sent)) >= 4 and sent.count(",") >= 3


def hits(skill, axes, neg, pos):
    """Yield (axis, polarity, weight, line_no, excerpt) per sentence that names an axis.
    Skips frontmatter, code blocks and heading lines (headings only set the section context)."""
    levels, label_ctx, lead_ctx, in_code, seen_heading = {}, 0, 0, False, False
    for idx in range(skill["body_start"], len(skill["lines"])):
        raw, ln = skill["lines"][idx], idx + 1
        stripped = raw.strip()
        if stripped.startswith(("```", "~~~")):
            in_code = not in_code
            continue
        if in_code or not stripped:
            continue
        h = HEADING.match(stripped)
        if h:
            lvl = len(h.group(1))
            levels = {k: v for k, v in levels.items() if k < lvl}
            # the document title ("# Anti-Slop Frontend Skill") names the skill, it does not open an avoid list
            levels[lvl] = section_ctx(h.group(2)) if seen_heading or lvl > 1 else 0
            seen_heading = True
            label_ctx = lead_ctx = 0
            continue
        is_item = bool(LIST_ITEM.match(raw))
        b = BOLD_LABEL.match(stripped)
        if b and not is_item:
            label_ctx = section_ctx(b.group(1))
        heading_ctx = next((levels[k] for k in sorted(levels, reverse=True) if levels[k]), 0)
        ctx = (lead_ctx if is_item else 0) or label_ctx or heading_ctx
        line_pol = 0
        for sent in SENT_SPLIT.split(raw):
            if not sent.strip():
                continue
            spans = polarity_spans(sent, neg, pos)
            line_pol = line_pol or nearest(spans, len(sent))
            for axis, ax in axes.items():
                s2 = sent
                for ex in ax["exclude"]:
                    s2 = ex.sub(lambda m: " " * len(m.group(0)), s2)
                m = next((m for m in (rx.search(s2) for rx in ax["include"]) if m), None)
                if not m or is_name(sent, m):
                    continue
                p = resolve(sent, spans, m.start(), ctx)
                if p:
                    w = 2 if p < 0 and STRONG.search(sent) else 1
                    yield axis, p, w, ln, excerpt(sent, m.start())
        if stripped.endswith((":", "：")):
            lead_ctx = line_pol
        elif not is_item:
            lead_ctx = 0


def decide(rec, avo):
    """Weighted totals -> stance. Both sides within 1:2..2:1 is mixed."""
    if not rec and not avo:
        return None
    if rec and avo and 0.5 <= rec / avo <= 2:
        return "mixed"
    return "recommends" if rec > avo else "avoids"


def stance_table(skills, lexicon=None):
    """{axis: {skill: {"stance", "rec", "avo", "best": {+1/-1: (weight, line, excerpt)}}}}"""
    axes, neg, pos = load_lexicon(lexicon)
    tab = {a: {} for a in axes}
    for s in skills:
        for axis, p, w, ln, ex in hits(s, axes, neg, pos):
            c = tab[axis].setdefault(s["name"], {"rec": 0, "avo": 0, "best": {}})
            c["rec" if p > 0 else "avo"] += w
            if w > c["best"].get(p, (0,))[0]:
                c["best"][p] = (w, ln, ex)
    for axis in tab:
        for c in tab[axis].values():
            c["stance"] = decide(c["rec"], c["avo"])
    return tab


def clashing(tab):
    """Axes where one skill recommends and another avoids."""
    return [a for a, row in tab.items()
            if {"recommends", "avoids"} <= {c["stance"] for c in row.values()}]


def evidence(cell):
    st = cell["stance"]
    p = +1 if st == "recommends" else -1 if st == "avoids" else max(cell["best"], key=lambda k: cell["best"][k][0])
    return cell["best"][p]


def fmt_table(tab, names):
    """Rows = axes with any stance, columns = skills (numbered, legend above)."""
    rows = [a for a, row in tab.items() if any(n in row for n in names)]
    if not rows:
        return "no stance found on any axis"
    w = max(len(a) for a in rows)
    out = [f"  [{i}] {n}" for i, n in enumerate(names, 1)]
    out += ["", f"  {'axis':<{w}} | " + " | ".join(f"{i:^3}" for i in range(1, len(names) + 1))]
    out.append(f"  {'-' * w}-+-" + "-+-".join("---" for _ in names))
    for a in rows:
        cells = [SYMBOL.get(tab[a].get(n, {}).get("stance"), "") for n in names]
        out.append(f"  {a:<{w}} | " + " | ".join(f"{c:^3}" for c in cells))
    return "\n".join(out)


def fmt_compact(tab, axes):
    """One line per axis for --all, where a full table would be too wide."""
    out = []
    for a in axes:
        out.append(f"  {a}")
        for st in ("recommends", "avoids", "mixed"):
            ns = sorted(n for n, c in tab[a].items() if c["stance"] == st)
            if ns:
                out.append(f"    {SYMBOL[st]} {', '.join(ns)}")
    return "\n".join(out)


def fmt_evidence(tab, names=None):
    out = []
    for a in clashing(tab):
        out.append(f"[{a}]")
        for n, c in sorted(tab[a].items(), key=lambda kv: ("recommends", "avoids", "mixed").index(kv[1]["stance"])):
            if names is None or n in names:
                _, ln, ex = evidence(c)
                out.append(f"  {SYMBOL[c['stance']]} {n} L{ln}: {ex}")
    return "\n".join(out)


# ---------- budget / plan ----------
def budget(sel, limit):
    total = sum(s["words"] for s in sel)
    return {"skills": [(s["name"], s["words"]) for s in sel], "words": total,
            "tokens": round(total * 1.3), "limit": limit, "over": total > limit}


def fmt_budget(b):
    rows = [f"  {n:<32} {w:>7,} words" for n, w in b["skills"]]
    rows.append(f"  {'TOTAL':<32} {b['words']:>7,} words  (~{b['tokens']:,} tokens)")
    if b["over"]:
        rows.append(f"  WARNING: over the {b['limit']:,}-word budget. Expect instructions to be dropped or averaged.")
    return "\n".join(rows)



def plan(skills, task, limit, lexicon=None, k=5):
    t = task_tokens(task, load_aliases(lexicon))
    scored = []
    for s in skills:
        d = tokens(s["description"]) | tokens(s["name"].replace("-", " "))
        hit = t & d
        if hit:
            scored.append((round(len(hit) / len(t), 3), s, sorted(hit)))
    scored.sort(key=lambda x: (-x[0], x[1]["words"]))
    review = [x for x in scored if is_review(x[1]["description"])][:k]
    build = [x for x in scored if not is_review(x[1]["description"])][:k]
    tab = stance_table([x[1] for x in build + review], lexicon)
    best = None
    for b in build:
        for r in review:
            pair = {b[1]["name"], r[1]["name"]}
            n = sum(1 for row in tab.values()
                    if {"recommends", "avoids"} <= {c["stance"] for name, c in row.items() if name in pair})
            over = b[1]["words"] + r[1]["words"] > limit
            score = b[0] + r[0] - 0.1 * n - (0.2 if over else 0)
            if not best or score > best[0]:
                best = (score, b[1], r[1])
    if not best and build:
        best = (build[0][0], build[0][1], None)
    chosen = [x for x in best[1:3] if x] if best else []
    return {"build": build, "review": review, "best": best, "chosen": chosen,
            "table": stance_table(chosen, lexicon) if chosen else None,
            "budget": budget(chosen, limit) if chosen else None}


def needs_rewrite(s):
    d = s["description"]
    return bool(d) and not USE_FIRST.search(d[:80])


# ---------- output ----------
def emit(a, obj, text):
    """--json prints one JSON value on stdout; otherwise the human text. No colour, ever (NO_COLOR is trivially met)."""
    if getattr(a, "json", False):
        print(json.dumps(obj, ensure_ascii=False, indent=1))
    elif text:
        print(text)


def note(msg):
    print(msg, file=sys.stderr)


def cell_json(c):
    if not c:
        return {"stance": None, "line": None, "evidence": None}
    _, ln, ex = evidence(c)
    return {"stance": c["stance"], "line": ln, "evidence": ex}


def table_json(tab, names):
    return {axis: {n: cell_json(tab[axis].get(n)) for n in names if n in tab[axis]} for axis in tab
            if any(n in tab[axis] for n in names)}


# ---------- commands ----------
def cmd_scan(a):
    sk = sorted(load_skills(resolve_dirs(a)), key=lambda s: -s["words"])
    rows = [f"{'name':<36} {'words':>7} {'tokens':>7}  description"]
    rows += [f"{s['name']:<36} {s['words']:>7,} {s['tokens']:>7,}  {s['description'][:70]}" for s in sk]
    rows.append(f"\n{len(sk)} skills, {sum(s['words'] for s in sk):,} words total")
    emit(a, [{k: s[k] for k in ("name", "path", "description", "words", "tokens")} for s in sk], "\n".join(rows))
    return 0


def cmd_budget(a):
    sk = load_skills(resolve_dirs(a))
    b = budget([find(sk, n) for n in a.skills], a.max)
    emit(a, b, fmt_budget(b))
    return 1 if b["over"] else 0


def cmd_overlap(a):
    ov = overlap(load_skills(resolve_dirs(a)), a.min, a.top)
    emit(a, [{"a": x, "b": y, "jaccard": j, "shared": sh} for j, x, y, sh in ov],
         "\n".join(f"{j:.3f}  {x} ⇄ {y}   shared: {', '.join(sh[:12])}" for j, x, y, sh in ov) or "no pairs")
    return 0


def cmd_conflict(a):
    sk = load_skills(resolve_dirs(a))
    if not a.all:
        if not a.set:
            raise Fail("conflict: give --set <skill> <skill> ... (the skills you will load together) or --all")
        sk = [find(sk, n) for n in a.set]
    tab = stance_table(sk, a.lexicon)
    cl = clashing(tab)
    names = [s["name"] for s in sk]
    if a.all:
        out = [f"Axes where one skill recommends (✓) and another avoids (✗), across {len(sk)} skills:\n",
               fmt_compact(tab, cl) or "  none"]
    else:
        out = [fmt_table(tab, names)]
    out.append("\n✓ recommends  ✗ avoids  ~ mixed  (blank: no stance)")
    if cl:
        out += ["\nEvidence (one sentence per skill, open the line to check):", fmt_evidence(tab)]
    out.append(f"\n{len(cl)} axes with ✓ and ✗ in the same row")
    emit(a, {"skills": names, "stance": table_json(tab, names), "clashing": cl}, "\n".join(out))
    return 1 if cl else 0


def plan_text(p, task):
    out = [f"Task: {task}", "", "Build candidates:"]
    out += [f"  {sc:.2f}  {s['name']} ({s['words']:,} words)  matched: {', '.join(h[:8])}" for sc, s, h in p["build"]] or ["  (none)"]
    out += ["", "Review candidates:"]
    out += [f"  {sc:.2f}  {s['name']} ({s['words']:,} words)  matched: {', '.join(h[:8])}" for sc, s, h in p["review"]] or ["  (none)"]
    if p["best"]:
        _, b, r = p["best"]
        tab = p["table"]
        out += ["", f"Proposal: build = {b['name']}, review = {r['name'] if r else '(none found)'}", "",
                "Stances:", fmt_table(tab, [s["name"] for s in p["chosen"]]), "", "Budget:", fmt_budget(p["budget"])]
        if clashing(tab):
            out += ["", "Conflicts (decide which one wins before you start):", fmt_evidence(tab)]
        for s in (b, r):
            if s and needs_rewrite(s):
                out.append(f"Hint: {s['name']} description does not lead with when to use it; suggest rewriting it to start with 'Use when ...'.")
    return "\n".join(out)


def plan_json(p, task):
    cand = lambda xs: [{"name": s["name"], "score": sc, "words": s["words"], "matched": h} for sc, s, h in xs]
    names = [s["name"] for s in p["chosen"]]
    return {"task": task, "build": cand(p["build"]), "review": cand(p["review"]),
            "builder": names[0] if names else None, "checker": names[1] if len(names) > 1 else None,
            "clashing": clashing(p["table"]) if p["table"] else [], "budget": p["budget"],
            "stance": table_json(p["table"], names) if p["table"] else {}}


def cmd_plan(a):
    p = plan(load_skills(resolve_dirs(a)), a.task, a.max, a.lexicon)
    emit(a, plan_json(p, a.task), plan_text(p, a.task))
    return 1 if p["table"] and (clashing(p["table"]) or p["budget"]["over"]) else 0


def kind(s):
    d = s["description"]
    return "checker" if is_review(d) else "builder" if BUILD_HINT.search(d) else "other"


def report_json(sk, a):
    """One JSON file for other tools (key names are listed in docs/reference.md)."""
    tab = stance_table(sk, a.lexicon)
    return {
        "skills": [{"name": s["name"], "path": s["path"], "description": s["description"], "words": s["words"],
                    "tokens": s["tokens"], "kind": kind(s)} for s in sk],
        "overlap": [{"a": x, "b": y, "jaccard": j, "shared": sh} for j, x, y, sh in overlap(sk, a.min, top=10 ** 6)],
        "stance": {s["name"]: {axis: cell_json(tab[axis].get(s["name"])) for axis in tab} for s in sk},
        "axes": list(tab),
        "budget_limit": a.max,
    }


# ---------- loadout ----------
def pick_pair(sel, limit, tab):
    """Same rule as plan() without the task score: among the set, the builder/checker pair with
    the fewest clashing axes, minus 0.2 when over budget; ties go to set order."""
    build = [s for s in sel if not is_review(s["description"])] or sel[:1]
    review = [s for s in sel if is_review(s["description"])]
    best = None
    for b in build:
        for r in [x for x in review if x is not b] or [None]:
            pair = {b["name"], r["name"] if r else None}
            n = sum(1 for row in tab.values()
                    if {"recommends", "avoids"} <= {c["stance"] for name, c in row.items() if name in pair})
            over = b["words"] + (r["words"] if r else 0) > limit
            score = -0.1 * n - (0.2 if over else 0)
            if not best or score > best[0]:
                best = (score, b, r)
    return best[1], best[2]


def loadout_md(sel, builder, checker, wins, tab, limit):
    """The LOADOUT.md text. report.html builds the same text in JS (loadoutMd); keep them in step."""
    names = [s["name"] for s in sel]
    rest = [n for n in names if n not in (builder, checker)]
    out = ["# LOADOUT（skill より先に読む）",
           f"作る用: {builder}（この1つだけの手順で作る）",
           f"点検用: {checker}（仕上げの点検にだけ使う）" if checker else "点検用: なし（set に点検用の skill がない）",
           f"読まない: {'、'.join(rest) or 'なし'}（必要な軸を直すときだけ読む）",
           "決めた向き（ぶつかる軸）:"]
    cl = clashing(tab)
    for axis in cl:
        row = {n: tab[axis][n] for n in names if n in tab[axis]}
        ref = lambda n: f"{n} L{evidence(row[n])[1]}"
        w = wins.get(axis)
        if w:
            st = row[w]["stance"]
            opp = "avoids" if st == "recommends" else "recommends"
            losers = "、".join(f"{ref(n)} の{'勧め' if opp == 'recommends' else '禁止'}" for n in row if row[n]["stance"] == opp)
            out.append(f"- {axis}: {'使う' if st == 'recommends' else '使わない'}（{w} に従う。{losers}は今回は採らない）")
        else:
            rec = "、".join(ref(n) for n in row if row[n]["stance"] == "recommends")
            avo = "、".join(ref(n) for n in row if row[n]["stance"] == "avoids")
            out.append(f"- {axis}: 未決（{rec} は勧める。{avo} は避ける。人が決める）")
    if not cl:
        out.append("- なし")
    read = sum(s["words"] for s in sel if s["name"] in (builder, checker))
    total = sum(s["words"] for s in sel)
    out.append(f"読む語数: {read:,} 語（作る用＋点検用。上限 {limit:,}）" + (f"。上限を {read - limit:,} 語超える" if read > limit else ""))
    if rest:
        out.append(f"候補を全部読むと: {total:,} 語")
    return "\n".join(out) + "\n"


RULES = Path(".claude/rules/skills-loadout.md")


def write_loadout(md, out, rules, force=False, dry_run=False):
    """Write LOADOUT.md; with rules, also a one-line .claude/rules file that Claude Code reads every session.
    An existing LOADOUT.md with other text is only replaced with force. Returns (path, written)."""
    out = Path(os.path.expanduser(out))
    if out.exists() and out.read_text(encoding="utf-8") != md and not force and not dry_run:
        raise Fail(f"{out} exists and differs; pass --force to replace it, or --dry-run to only print")
    if dry_run:
        return out, False
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    if rules:
        if RULES.exists():
            note(f"kept {RULES.resolve()} (already there)")
        else:
            RULES.parent.mkdir(parents=True, exist_ok=True)
            # @ paths resolve from the rules file, so a plain "@LOADOUT.md" would point into .claude/rules/
            RULES.write_text(f"@{os.path.relpath(out.resolve(), RULES.parent.resolve())}\n", encoding="utf-8")
            note(f"wrote {RULES.resolve()}")
    return out, True


def parse_hash(h):
    """The page's state for apply: set=a,b,c&b=x&c=y|-&win=axis:skill;axis:skill (a leading # or ? is fine)."""
    from urllib.parse import parse_qs
    q = {k: v[0] for k, v in parse_qs(h.lstrip("#?"), keep_blank_values=True).items()}
    wins = {}
    for kv in filter(None, q.get("win", "").split(";")):
        axis, _, n = kv.rpartition(":")
        if n != "-":
            wins[axis] = n
    return [n for n in q.get("set", "").split(",") if n], q.get("b") or None, q.get("c") or None, wins


def cmd_apply(a):
    names, b, c, wins = parse_hash(a.hash)
    if not names:
        raise Fail("apply: the hash has no set=. Copy the command from step 5 of the page.")
    a.set, a.builder, a.win = names, b, [f"{k}={v}" for k, v in wins.items()]
    a.checker = None if c == "-" else c
    a.no_checker = c == "-"
    return cmd_loadout(a)


def cmd_triggers(a):
    rows = sorted((s for s in load_skills(resolve_dirs(a)) if s["description"] and not TRIGGER.search(s["description"][:160])),
                  key=lambda s: s["name"])
    text = "\n".join(f"{s['name']:<36} {s['description'][:90]}" for s in rows)
    emit(a, [{"name": s["name"], "description": s["description"]} for s in rows],
         text + f"\n\n{len(rows)} skills do not say when to use them in the first 160 characters of the description")
    return 0


def cmd_loadout(a):
    sk = load_skills(resolve_dirs(a))
    sel = [find(sk, n) for n in a.set]
    tab = stance_table(sel, a.lexicon)
    b, c = pick_pair(sel, a.max, tab)
    builder = find(sel, a.builder)["name"] if a.builder else b["name"]
    checker = None if getattr(a, "no_checker", False) else find(sel, a.checker)["name"] if a.checker else c["name"] if c and c["name"] != builder else None
    cl, wins = clashing(tab), {}
    for w in a.win or []:
        axis, _, n = w.rpartition("=")
        if axis not in cl:
            raise Fail(f"--win {w}: '{axis}' is not a clashing axis in this set ({', '.join(cl) or 'none'})")
        n = find(sel, n)["name"]
        if tab[axis].get(n, {}).get("stance") not in ("recommends", "avoids"):
            raise Fail(f"--win {w}: {n} has no ✓ or ✗ on {axis}")
        wins[axis] = n
    md = loadout_md(sel, builder, checker, wins, tab, a.max)
    out, written = write_loadout(md, a.out, a.rules, getattr(a, "force", False), getattr(a, "dry_run", False))
    undecided = len(cl) - len(wins)
    over = sum(s["words"] for s in sel if s["name"] in (builder, checker)) > a.max
    emit(a, {"path": str(out.resolve()), "written": written, "builder": builder, "checker": checker,
             "undecided": [x for x in cl if x not in wins], "over_budget": over, "loadout": md}, md.rstrip("\n"))
    note(f"{'wrote' if written else 'dry run, not written:'} {out.resolve()}  ({undecided} axes undecided)")
    return 1 if undecided or over else 0


def report_html(data, lexicon=None):
    """report_template.html with the report JSON and the ja_en word list embedded; one file, no network."""
    js = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    al = json.dumps(load_aliases(lexicon), ensure_ascii=False).replace("</", "<\\/")
    return ((HERE / "scripts" / "report_template.html").read_text(encoding="utf-8")
            .replace("/*DATA*/null", js).replace("/*ALIAS*/null", al))


WORKDIR = Path(".skill-clash")


def cmd_report(a):
    sk = load_skills(resolve_dirs(a))
    if a.html:
        out = Path(os.path.expanduser(a.html))
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report_html(report_json(sk, a), a.lexicon), encoding="utf-8")
        note(f"wrote {out.resolve()}  ({len(sk)} skills)")
        return 0
    if a.json:
        if a.json == "-":
            print(json.dumps(report_json(sk, a), ensure_ascii=False, indent=1))
            return 0
        out = Path(os.path.expanduser(a.json))
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report_json(sk, a), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        note(f"wrote {out.resolve()}  ({len(sk)} skills)")
        return 0
    md = ["# skill-clash report", "", f"Scanned {len(sk)} skills in: {', '.join(resolve_dirs(a))}", "",
          "## Size (largest first)", "", "| skill | words | ~tokens |", "|---|---:|---:|"]
    md += [f"| {s['name']} | {s['words']:,} | {s['tokens']:,} |" for s in sorted(sk, key=lambda s: -s["words"])]
    for combo in a.combo or []:
        sel = [find(sk, n.strip()) for n in combo.split(",")]
        tab = stance_table(sel, a.lexicon)
        md += ["", f"## Set: {combo}", "", "```", fmt_table(tab, [s["name"] for s in sel]), "", fmt_budget(budget(sel, a.max)), "```"]
        if clashing(tab):
            md += ["", "```", fmt_evidence(tab), "```"]
    md += ["", f"## Trigger overlap (Jaccard >= {a.min}, top 20)", ""]
    md += [f"- {j:.3f} **{x}** ⇄ **{y}** — shared: {', '.join(s[:12])}" for j, x, y, s in overlap(sk, a.min)] or ["- none"]
    tab = stance_table(sk, a.lexicon)
    cl = clashing(tab)
    md += ["", f"## Stances across all skills ({len(cl)} axes with ✓ and ✗)", "",
           "Heuristic: each skill gets one stance per axis from weighted sentence cues. Check the evidence lines.", "",
           "```", fmt_compact(tab, cl) or "none", "", fmt_evidence(tab), "```"]
    rw = [s["name"] for s in sk if needs_rewrite(s)]
    md += ["", "## Descriptions that do not lead with when to use them", "", ", ".join(rw) or "none"]
    if a.task:
        md += ["", "## Plan", "", "```", plan_text(plan(sk, a.task, a.max, a.lexicon), a.task), "```"]
    out = WORKDIR / "report.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text("\n".join(md) + "\n", encoding="utf-8")
    note(f"wrote {out.resolve()}  ({len(sk)} skills, {len(cl)} axes with ✓ and ✗)")
    return 0


# ---------- bench: precision / recall against a hand-labelled gold set ----------
GOLD = HERE / "tests" / "gold" / "cells.jsonl"


def mentions(skill, axis, axes, limit=8):
    """Body lines that name the axis (excludes applied), for a person to judge the cell."""
    ax, out = axes[axis], []
    for idx in range(skill["body_start"], len(skill["lines"])):
        line = skill["lines"][idx]
        s2 = line
        for ex in ax["exclude"]:
            s2 = ex.sub(lambda m: " " * len(m.group(0)), s2)
        if any(rx.search(s2) for rx in ax["include"]):
            out.append((idx + 1, line.strip()[:300]))
    return out[:limit]


def wilson(k, n, z=1.96):
    if not n:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(c - h, 3), round(c + h, 3))


def draw_cells(sk, n_stance, n_none, seed, lexicon=None):
    """Random cells for a new gold set: n_stance with ✓✗~, n_none with no stance but a mention of the axis
    (a cell with no mention at all is trivially empty and would say nothing about recall)."""
    axes, _, _ = load_lexicon(lexicon)
    tab = stance_table(sk, lexicon)
    rng = random.Random(seed)
    with_st, without = [], []
    for s in sk:
        for axis in axes:
            c = tab[axis].get(s["name"])
            if c and c["stance"]:
                with_st.append((s, axis, c["stance"]))
            elif mentions(s, axis, axes, 1):
                without.append((s, axis, None))
    picked = rng.sample(with_st, min(n_stance, len(with_st))) + rng.sample(without, min(n_none, len(without)))
    home = os.path.expanduser("~")
    return [{"id": i + 1, "skill": s["name"], "path": s["path"].replace(home, "~", 1), "axis": axis, "pred_at_draw": st,
             "lines": [ln for ln, _ in mentions(s, axis, axes)], "text": [t for _, t in mentions(s, axis, axes)],
             "gold": "", "note": ""} for i, (s, axis, st) in enumerate(picked)]


def bench(rows, lexicon=None):
    """Exact-stance precision and recall: a cell counts as right only when the stance matches the label."""
    tp_p = n_p = tp_r = n_r = 0
    misses, skipped = [], 0
    cache = {}
    for r in rows:
        if r.get("gold") in (None, "", "uncertain"):
            continue
        path = os.path.expanduser(r["path"])
        if not Path(path).is_file():
            skipped += 1
            continue
        s = cache.get(path) or cache.setdefault(path, read_skill(path))
        s = dict(s, name=r["skill"])
        c = stance_table([s], lexicon)[r["axis"]].get(r["skill"])
        pred = c["stance"] if c else None
        gold = None if r["gold"] == "none" else r["gold"]
        if pred:
            n_p += 1
            tp_p += pred == gold
        if gold:
            n_r += 1
            tp_r += pred == gold
        if pred != gold:
            misses.append({"id": r["id"], "skill": r["skill"], "axis": r["axis"], "pred": pred, "gold": gold})
    return {"precision": round(tp_p / n_p, 3) if n_p else None, "precision_n": n_p, "precision_ci95": wilson(tp_p, n_p),
            "recall": round(tp_r / n_r, 3) if n_r else None, "recall_n": n_r, "recall_ci95": wilson(tp_r, n_r),
            "labelled": sum(1 for r in rows if r.get("gold") not in (None, "", "uncertain")),
            "uncertain": sum(1 for r in rows if r.get("gold") == "uncertain"), "skipped_missing_file": skipped,
            "misses": misses}


def cmd_bench(a):
    path = Path(os.path.expanduser(a.gold)) if a.gold else GOLD
    if a.draw:
        rows = draw_cells(load_skills(resolve_dirs(a)), a.draw[0], a.draw[1], a.seed, a.lexicon)
        if path.exists() and not a.force:
            raise Fail(f"{path} exists; pass --force to draw a new set over it")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
        note(f"wrote {path} ({len(rows)} cells, seed {a.seed}); fill in gold: recommends / avoids / mixed / none / uncertain")
        return 0
    if not path.is_file():
        raise Fail(f"no gold set at {path}; draw one with --draw 40 20")
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    r = bench(rows, a.lexicon)
    pct = lambda x: "n/a" if x is None else f"{x:.1%}"
    text = [f"Gold set: {path} ({r['labelled']} labelled, {r['uncertain']} uncertain left out, {r['skipped_missing_file']} skipped: file missing)",
            f"Precision {pct(r['precision'])}  (n={r['precision_n']}, 95% Wilson {r['precision_ci95'][0]:.1%}–{r['precision_ci95'][1]:.1%})",
            f"Recall    {pct(r['recall'])}  (n={r['recall_n']}, 95% Wilson {r['recall_ci95'][0]:.1%}–{r['recall_ci95'][1]:.1%})"]
    text += [f"  miss #{m['id']} {m['skill']} / {m['axis']}: tool {m['pred']}, label {m['gold']}" for m in r["misses"]]
    emit(a, r, "\n".join(text))
    return 1 if r["precision"] is not None and r["precision"] < 0.9 else 0


# ---------- place: where each skill belongs ----------
PLACES = {"trunk": "幹（常に効かせる。入口・束ね役）", "scene": "場面（そのまま。description で呼ばれる）",
          "name-only": "名前だけ（skillOverrides で name-only）", "drop": "外す候補（off か、リンクを外す）"}
TRUNK = re.compile(r"(skill|スキル).{0,40}(より先|の前に|入口|を選|束ね|経路)|より先にこれ|入口|前.{0,2}に必ず|\bread (this )?first\b|"
                   r"\borchestrat\w*|\broutes? [^.]{0,40}\bto the (right|best|correct)\b|find and use skills|before (any )?(other )?skills?", re.I)
# "replaced X", "X is deprecated", "X を置き換えた", "X のリンクを外した": the name next to the verb is the old one
REPLACED_AFTER = r"\b(replac\w*|supersed\w*|deprecat\w*|retir\w*)\b\W{0,3}"
REPLACED_BEFORE = r"(\W{0,3}(is|was|has been|are|were) (now )?(deprecated|replaced|superseded|obsolete|retired)\b|.{0,30}?(置き換え|廃止|外した|使わなくな))"
# shortcut: one query per kind, matched like plan; extend the list when a new kind of work shows up
KINDS = [("アプリ・ツール・管理画面", "dashboard admin app interface tool settings"),
         ("LP・Web サイト", "landing page website marketing"),
         ("スライド・資料", "slides presentation deck"),
         ("動画", "video"),
         ("図・構成図", "diagram architecture"),
         ("日本語の文章", "日本語 文章 推敲 document writing")]


def place(sk, broken=(), min_j=0.25, lexicon=None, limit=6000):
    """One place per skill with the rules that put it there. Precedence: drop > trunk > name-only > scene."""
    names = {s["name"] for s in sk}
    rules = {s["name"]: [] for s in sk}
    big = sorted(s["words"] for s in sk)[int(len(sk) * 0.95)] if sk else 0
    replaced = {}
    for s in sk:  # another skill's body says it replaced this one
        for idx in range(s["body_start"], len(s["lines"])):
            line = s["lines"][idx]
            for n in names - {s["name"]}:
                short = re.escape(n.split(":")[-1].split("@")[0])
                if len(short) >= 5 and re.search(rf"{REPLACED_AFTER}`?{short}(?![\w-])|(?<![\w-]){short}`?{REPLACED_BEFORE}", line, re.I):
                    replaced.setdefault(n, f"{s['name']} L{idx + 1} に置き換え・廃止の記述: {line.strip()[:80]}")
    losers = {}
    for j, x, y, _ in overlap(sk, min_j, top=10 ** 6):
        sx, sy = next(s for s in sk if s["name"] == x), next(s for s in sk if s["name"] == y)
        # a builder and a checker do not compete; between two of a kind, the one that cannot win selection
        # is the one with no when-to-use up front, else the larger one; a full tie names no loser
        key = lambda s: (bool(TRIGGER.search(s["description"][:160])), -s["words"])
        if is_review(sx["description"]) != is_review(sy["description"]) or key(sx) == key(sy):
            continue
        lo, hi = (sx, sy) if key(sx) < key(sy) else (sy, sx)
        losers.setdefault(lo["name"], f"description が {hi['name']} と重なる（Jaccard {j:.2f}）。選ばれるのは向こう")
    out = []
    for s in sk:
        n, d, r = s["name"], s["description"], rules[s["name"]]
        when = bool(d) and bool(TRIGGER.search(d[:160]))
        if n in replaced:
            r.append(("drop", replaced[n]))
        if s["words"] >= big and not when:
            r.append(("drop", f"語数 {s['words']:,} は上位5%（{big:,} 語以上）で、description に呼ばれる場面がない"))
        if TRUNK.search(d):
            r.append(("trunk", f"description がほかの skill を束ねる: 「{TRUNK.search(d).group(0)}」"))
        if not when:
            r.append(("name-only", "description の先頭160字に「いつ使うか」がない"))
        if n in losers:
            r.append(("name-only", losers[n]))
        if s.get("dup"):
            r.append(("name-only", "同じ名前の別の版がある"))
        if not r:
            r.append(("scene", "先頭に「いつ使うか」があり、重なりが 0.25 未満"))
        order = ["drop", "trunk", "name-only", "scene"]
        out.append({"name": n, "path": s["path"], "words": s["words"], "place": min((p for p, _ in r), key=order.index),
                    "rules": [f"{p}: {why}" for p, why in r]})
    for b in broken:
        out.append({"name": b.name, "path": str(b), "words": 0, "place": "drop", "rules": ["drop: リンク切れ（上流で消えた）"]})
    overrides = {o["name"]: "off" if o["place"] == "drop" else "name-only"
                 for o in out if o["place"] in ("drop", "name-only") and Path(o["path"]).exists()}
    pool = [s for s in sk if next(o for o in out if o["name"] == s["name"])["place"] in ("scene", "name-only")]
    routes = []
    for label, q in KINDS:
        p = plan(pool, q, limit, lexicon, k=3)
        ch = [s["name"] for s in p["chosen"]]
        # a checker that shares one word with the kind (pr-to-video for "video") is noise, not a route
        strong = {s["name"] for _, s, h in p["review"] if len(h) >= 2}
        routes.append({"kind": label, "builder": ch[0] if ch else None,
                       "checker": ch[1] if len(ch) > 1 and ch[1] in strong else None})
    return {"skills": out, "skillOverrides": overrides, "routes": routes}


def place_md(r):
    out = ["# skill の置き場所（下書き。人が決める。settings.json は自動で書かない）", ""]
    for key, label in PLACES.items():
        rows = [o for o in r["skills"] if o["place"] == key]
        out += [f"## {label} — {len(rows)}", ""]
        for o in sorted(rows, key=lambda o: o["name"]):
            out.append(f"- **{o['name']}**（{o['words']:,} 語）")
            out += [f"  - {x}" for x in o["rules"]]
        out.append("")
    out += ["## settings.json に貼る片（確かめてから）", "", "```json",
            json.dumps({"skillOverrides": r["skillOverrides"]}, ensure_ascii=False, indent=2), "```", "",
            "## 経路表の下書き（種類 → 作る用／点検用）", "", "| 種類 | 作る用の skill（1つだけ） | 点検用 |", "|---|---|---|"]
    out += [f"| {x['kind']} | {x['builder'] or '（候補なし）'} | {x['checker'] or '（候補なし）'} |" for x in r["routes"]]
    return "\n".join(out) + "\n"


def cmd_place(a):
    dirs = resolve_dirs(a)
    sk = load_skills(dirs)
    broken = [p for d in dirs for p in sorted(Path(os.path.expanduser(d)).glob("*"))
              if p.is_symlink() and not p.exists()] if Path(os.path.expanduser(dirs[0])).is_dir() else []
    r = place(sk, broken, a.min, a.lexicon, a.max)
    md = place_md(r)
    if a.out:
        out = Path(os.path.expanduser(a.out))
        if out.exists() and not a.force:
            raise Fail(f"{out} exists; pass --force to replace it")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(md, encoding="utf-8")
        note(f"wrote {out.resolve()}")
    counts = {k: sum(1 for o in r["skills"] if o["place"] == k) for k in PLACES}
    emit(a, r, md if not a.out else "  ".join(f"{k}: {v}" for k, v in counts.items()))
    return 0


def cmd_selftest(a):
    import contextlib, io, tempfile
    quiet = lambda: contextlib.ExitStack()
    fx = str(HERE / "tests" / "fixtures")
    sk = load_skills([fx])
    names = sorted(s["name"] for s in sk)
    assert names == ["alpha", "beta", "delta", "epsilon", "eta", "gamma"], names
    tab = stance_table(sk)
    st = lambda axis, n: tab[axis].get(n, {}).get("stance")
    # (a) "## Avoid" heading -> the bare list item "- gradients ..." avoids
    assert st("gradient", "delta") == "avoids", tab["gradient"]
    # (b) a skill that names gradient only in a heading, and (c) only in a theme-name list, has no stance
    assert st("gradient", "epsilon") is None, tab["gradient"].get("epsilon")
    # (d) "never use gradients" avoids, with the strong-ban weight
    assert st("gradient", "eta") == "avoids" and tab["gradient"]["eta"]["avo"] == 2, tab["gradient"].get("eta")
    # (e) "use a subtle gradient" recommends
    assert st("gradient", "beta") == "recommends", tab["gradient"].get("beta")
    # (f) the real-world pairs show up in a --set table
    sel = [find(sk, n) for n in ("alpha", "beta", "gamma")]
    t3 = stance_table(sel)
    assert st("serif", "alpha") == "recommends" and t3["serif"]["beta"]["stance"] == "avoids", t3["serif"]
    assert t3["cream / beige background"]["alpha"]["stance"] == "recommends"
    assert t3["cream / beige background"]["beta"]["stance"] == "avoids"
    assert t3["card grid / bento"]["gamma"]["stance"] == "recommends"
    assert t3["card grid / bento"]["beta"]["stance"] == "avoids"
    assert {"serif", "cream / beige background", "card grid / bento", "gradient"} <= set(clashing(t3)), clashing(t3)
    table = fmt_table(t3, ["alpha", "beta", "gamma"])
    assert "serif" in table and "✓" in table and "✗" in table, table
    # sans-serif must not count as serif; "don't use emoji" must not be read as "use"
    assert "gamma" not in t3["serif"], t3["serif"]
    assert st("emoji", "alpha") == "avoids" and "emoji" not in clashing(t3), tab["emoji"]
    # weighting: 1:2..2:1 is mixed
    assert decide(2, 1) == "mixed" and decide(1, 3) == "avoids" and decide(3, 1) == "recommends" and decide(0, 0) is None
    ov = overlap(sk, 0.25)
    assert any({x, y} == {"alpha", "gamma"} for _, x, y, _ in ov), ov
    assert not any("beta" in (x, y) for _, x, y, _ in ov), ov
    b = budget(sk, 50)
    assert b["over"] and b["words"] == sum(s["words"] for s in sk), b
    assert not budget([find(sk, "alpha")], 6000)["over"]
    assert count_words("日本語の文章です") == 4 and count_words("one two three") == 3
    p = plan(sk, "build a landing page with editorial serif headings", 6000)
    assert p["best"][1]["name"] == "alpha" and p["best"][2]["name"] == "beta", p["best"]
    assert "serif" in clashing(p["table"]), p["table"]
    # Japanese requests: particles do not match, ja_en brings the English words (same list as the page)
    tt = task_tokens("高級感のある LP", load_aliases())
    assert "ある" not in tt and "のあ" not in tt and {"landing", "premium", "高級"} <= tt, tt
    jp = plan(sk, "LP を作る", 6000)  # no English word at all: only ja_en can find the landing-page skills
    assert jp["best"] and jp["best"][1]["name"] in ("alpha", "gamma") and not any(set(h) & {"を作", "作る"} for _, _, h in jp["build"]), jp["build"]
    json.dumps(plan_json(p, "x"))
    class A: lexicon, min, max = None, 0.25, 6000
    j = report_json(sk, A)
    assert set(j) == {"skills", "overlap", "stance", "axes", "budget_limit"}, j.keys()
    assert {x["name"]: x["kind"] for x in j["skills"]}["beta"] == "checker"
    assert j["stance"]["delta"]["gradient"]["stance"] == "avoids" and j["stance"]["delta"]["gradient"]["line"] == 10
    assert j["stance"]["epsilon"]["gradient"] == {"stance": None, "line": None, "evidence": None}
    json.dumps(j)
    # loadout: builder/checker guessed like plan, a decided axis names the loser's line, the rest stay open
    t3 = stance_table(sel)
    bb, cc = pick_pair(sel, 6000, t3)
    assert (bb["name"], cc["name"]) == ("alpha", "beta"), (bb["name"], cc["name"])
    md = loadout_md(sel, "alpha", "beta", {"serif": "beta"}, t3, 6000)
    assert md.startswith("# LOADOUT（skill より先に読む）\n作る用: alpha（") and "読まない: gamma（" in md, md
    assert "- serif: 使わない（beta に従う。alpha L9 の勧めは今回は採らない）" in md, md
    assert "- gradient: 未決（beta L12 は勧める。gamma L10 は避ける。人が決める）" in md, md
    assert md.count("未決") == 3 and re.search(r"読む語数: [\d,]+ 語（作る用＋点検用。上限 6,000）\n候補を全部読むと: [\d,]+ 語\n$", md), md
    # apply: the page's hash gives the same LOADOUT.md as loadout; --rules writes the rules file once;
    # --dry-run writes nothing; a different existing LOADOUT.md needs --force; exit 1 while axes are undecided
    cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        try:
            class L: dirs, no_defaults, lexicon, max, out, rules, json, force, dry_run = [fx], True, None, 6000, "LOADOUT.md", True, False, False, True
            L.hash = "#set=alpha,beta,gamma&b=alpha&c=beta&win=serif:beta;gradient:-"
            sink = io.StringIO()
            with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
                assert cmd_apply(L) == 1
                assert not Path("LOADOUT.md").exists() and not RULES.exists(), "dry run wrote a file"
                L.dry_run = False
                cmd_apply(L)
                assert Path("LOADOUT.md").read_text(encoding="utf-8") == md, Path("LOADOUT.md").read_text(encoding="utf-8")
                assert RULES.read_text(encoding="utf-8") == "@../../LOADOUT.md\n", RULES.read_text(encoding="utf-8")
                RULES.write_text("keep\n", encoding="utf-8")
                cmd_apply(L)  # same text: no --force needed
                assert RULES.read_text(encoding="utf-8") == "keep\n", "rules file must not be overwritten"
                Path("LOADOUT.md").write_text("mine\n", encoding="utf-8")
                try:
                    cmd_apply(L)
                    raise AssertionError("overwrote LOADOUT.md without --force")
                except Fail:
                    pass
                L.force = True
                cmd_apply(L)
                assert Path("LOADOUT.md").read_text(encoding="utf-8") == md
        finally:
            os.chdir(cwd)
    # triggers: a description that says when to use it is fine, one that only says what it is is listed
    assert TRIGGER.search("Use when building a page") and TRIGGER.search("LP を作るときに使う")
    assert not TRIGGER.search("Clean editorial-style interfaces. Warm monochrome palette.")
    # html: one file, the embedded JSON parses back to the report keys, the word list is the lexicon's
    j["skills"][0]["description"] = "</script><b>x"  # must not end the script tag early
    html = report_html(j)
    m = re.search(r'<script type="application/json" id="data">(.*?)</script>', html, re.S)
    assert m and json.loads(m.group(1))["skills"][0]["description"] == "</script><b>x", "embedded JSON"
    assert not re.search(r"<(script|link)[^>]+(src|href)=\"https?:", html), "no network"
    assert "/*ALIAS*/" not in html and json.dumps(load_aliases()[0], ensure_ascii=False) in html, "ja_en list embedded"
    # bench: exact stance precision/recall, uncertain left out, Wilson interval
    assert wilson(0, 0) == (0.0, 0.0) and wilson(10, 10)[1] == 1.0 and wilson(9, 10) == (0.596, 0.982)  # textbook value 0.5958–0.9821
    path = lambda n: find(sk, n)["path"]
    gold = [{"id": 1, "skill": "delta", "path": path("delta"), "axis": "gradient", "gold": "avoids"},
            {"id": 2, "skill": "beta", "path": path("beta"), "axis": "gradient", "gold": "avoids"},     # tool says recommends
            {"id": 3, "skill": "epsilon", "path": path("epsilon"), "axis": "gradient", "gold": "none"},
            {"id": 4, "skill": "gamma", "path": path("gamma"), "axis": "serif", "gold": "recommends"},  # tool says nothing
            {"id": 5, "skill": "alpha", "path": path("alpha"), "axis": "serif", "gold": "uncertain"}]
    r = bench(gold)
    assert (r["precision_n"], r["recall_n"], r["labelled"], r["uncertain"]) == (2, 3, 4, 1), r
    assert r["precision"] == 0.5 and r["recall"] == round(1 / 3, 3) and len(r["misses"]) == 2, r
    # place: trunk, replaced -> drop, no when-to-use -> name-only, the rest stays; overrides and routes come out
    with tempfile.TemporaryDirectory() as tmp:
        def mk(n, desc, body):
            d = Path(tmp) / n
            d.mkdir()
            (d / "SKILL.md").write_text(f"---\nname: {n}\ndescription: {desc}\n---\n\n{body}\n", encoding="utf-8")
        mk("hub", "Use when any design work starts; read this before any other skill and pick one to build with.", "# Hub\nWe replaced oldkit with newkit.")
        mk("oldkit", "Use when you build a landing page the old way.", "# Old kit with a longer body than the new one")
        mk("newkit", "Use when you build a landing page website.", "# New")
        mk("vague", "Editorial interfaces with warm palettes.", "# Vague")
        mk("checky", "Review a landing page for accessibility problems. Use when a page is done.", "# Check")
        r = place(load_skills([tmp]))
        at = {o["name"]: o["place"] for o in r["skills"]}
        assert at == {"hub": "trunk", "oldkit": "drop", "newkit": "scene", "vague": "name-only", "checky": "scene"}, r["skills"]
        assert r["skillOverrides"] == {"oldkit": "off", "vague": "name-only"}, r["skillOverrides"]
        lp = next(x for x in r["routes"] if x["kind"].startswith("LP"))
        assert lp["builder"] == "newkit" and lp["checker"] == "checky", lp
        assert all(o["rules"] for o in r["skills"]) and "skillOverrides" in place_md(r)
    emit(a, {"ok": True}, "selftest OK")
    return 0


EXAMPLES = {
    None: """examples:
  skill_clash.py plan --task "build a landing page for a cafe"
  skill_clash.py conflict --set design-taste-frontend impeccable
  skill_clash.py place --out .skill-clash/place.md
  skill_clash.py bench

exit codes: 0 no problem, 1 clash or over budget (or bench precision < 90%), 2 error""",
    "scan": "examples:\n  skill_clash.py scan\n  skill_clash.py scan --json --dirs ~/.agents/skills",
    "budget": "examples:\n  skill_clash.py budget impeccable interface-design\n  skill_clash.py budget a b --max 4000 --json",
    "overlap": "examples:\n  skill_clash.py overlap\n  skill_clash.py overlap --min 0.3 --top 5 --json",
    "conflict": "examples:\n  skill_clash.py conflict --set design-taste-frontend impeccable\n  skill_clash.py conflict --all --json",
    "plan": "examples:\n  skill_clash.py plan --task \"build a landing page for a cafe\"\n  skill_clash.py plan --task \"高級感のある LP\" --json",
    "report": "examples:\n  skill_clash.py report --html .skill-clash/report.html\n  skill_clash.py report --json > report.json",
    "loadout": "examples:\n  skill_clash.py loadout --set a b c --win gradient=a --dry-run\n  skill_clash.py loadout --set a b --out LOADOUT.md --rules --force",
    "apply": "examples:\n  skill_clash.py apply '#set=a,b&b=a&c=b' --dry-run\n  skill_clash.py apply '#set=a,b&b=a&c=b&win=serif:b' --rules",
    "triggers": "examples:\n  skill_clash.py triggers\n  skill_clash.py triggers --json",
    "place": "examples:\n  skill_clash.py place\n  skill_clash.py place --out .skill-clash/place.md --json",
    "bench": "examples:\n  skill_clash.py bench\n  skill_clash.py bench --draw 40 20 --seed 7 --gold /tmp/new.jsonl",
    "selftest": "examples:\n  skill_clash.py selftest\n  skill_clash.py selftest --json",
}


def main(argv=None):
    fmt = argparse.RawDescriptionHelpFormatter
    ap = argparse.ArgumentParser(prog="skill_clash.py", description=__doc__, epilog=EXAMPLES[None], formatter_class=fmt)
    sub = ap.add_subparsers(dest="cmd", required=True)
    def add(name, fn, help):
        p = sub.add_parser(name, help=help, description=help, epilog=EXAMPLES[name], formatter_class=fmt)
        p.add_argument("--dirs", nargs="+", default=[], help=f"extra skill roots, added to the defaults ({USER_DIR} and enabled plugins)")
        p.add_argument("--no-defaults", action="store_true", help="scan only --dirs")
        if name != "report":
            p.add_argument("--json", action="store_true", help="print JSON on stdout (messages go to stderr)")
        p.set_defaults(fn=fn)
        return p
    def common(p, lexicon=True, mx=True):
        if mx:
            p.add_argument("--max", type=int, default=6000, help="word budget (default 6000)")
        if lexicon:
            p.add_argument("--lexicon", help="another lexicon.json")
    p = add("scan", cmd_scan, "size of every skill Claude sees")
    p = add("budget", cmd_budget, "combined size of a set; exit 1 when over --max"); p.add_argument("skills", nargs="+"); common(p, lexicon=False)
    p = add("overlap", cmd_overlap, "pairs whose descriptions share many words")
    p.add_argument("--min", type=float, default=0.25); p.add_argument("--top", type=int, default=20)
    p = add("conflict", cmd_conflict, "stance table (✓ ✗ ~) for a set; exit 1 when two skills disagree")
    p.add_argument("--set", nargs="+", help="the skills you will load together"); p.add_argument("--all", action="store_true", help="every scanned skill"); common(p, mx=False)
    p = add("plan", cmd_plan, "one builder and one checker for a one-line task"); p.add_argument("--task", required=True); common(p)
    p = add("report", cmd_report, "markdown report in .skill-clash/, or --json / --html")
    p.add_argument("--combo", action="append", help="comma-separated skills to table together (repeatable)")
    p.add_argument("--task"); p.add_argument("--min", type=float, default=0.25); common(p)
    p.add_argument("--json", nargs="?", const="-", metavar="PATH", help="write the report JSON to PATH (stdout when PATH is left out)")
    p.add_argument("--html", metavar="PATH", help="write one static HTML page (JSON embedded)")
    for name, fn, help in (("loadout", cmd_loadout, "write LOADOUT.md for a set"), ("apply", cmd_apply, "write the page's LOADOUT.md from its URL hash")):
        p = add(name, fn, help)
        if name == "loadout":
            p.add_argument("--set", nargs="+", required=True, help="the skills you will load together")
            p.add_argument("--builder"); p.add_argument("--checker")
            p.add_argument("--win", action="append", metavar="AXIS=SKILL", help="which skill wins a clashing axis (repeatable)")
        else:
            p.add_argument("hash", help="the page's URL hash (step 5 shows the full command)")
        common(p); p.add_argument("--out", default="LOADOUT.md")
        p.add_argument("--rules", action="store_true", help="also write .claude/rules/skills-loadout.md (@LOADOUT.md) unless it exists")
        p.add_argument("--force", action="store_true", help="replace a LOADOUT.md that has other text")
        p.add_argument("--dry-run", action="store_true", help="print, write nothing")
    add("triggers", cmd_triggers, "skills whose description does not say when to use them")
    p = add("place", cmd_place, "suggest trunk / scene / name-only / drop for every skill, with skillOverrides and a route table")
    p.add_argument("--out", metavar="PATH", help="write the markdown draft here"); p.add_argument("--force", action="store_true")
    p.add_argument("--min", type=float, default=0.25); common(p)
    p = add("bench", cmd_bench, "precision and recall of conflict against tests/gold/cells.jsonl; exit 1 under 90%%")
    p.add_argument("--gold", metavar="PATH"); p.add_argument("--draw", nargs=2, type=int, metavar=("STANCE", "NONE"), help="draw a new random gold set")
    p.add_argument("--seed", type=int, default=20261106); p.add_argument("--force", action="store_true"); common(p, mx=False)
    add("selftest", cmd_selftest, "assert-based tests on tests/fixtures")
    a = ap.parse_args(argv)
    try:
        return a.fn(a) or 0
    except Fail as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except (OSError, ValueError, re.error, AssertionError) as e:
        print(f"error: {type(e).__name__}: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
