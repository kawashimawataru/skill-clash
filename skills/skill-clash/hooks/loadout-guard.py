#!/usr/bin/env python3
"""PreToolUse hook (matcher: Skill). Claude も人と同じ LOADOUT.md を通す。

作業フォルダ（か、その親を4段まで）にある LOADOUT.md を読み、
「読まない」に挙がった skill を Skill ツールで読もうとしたら、理由つきで知らせる。
止めはしない（additionalContext）。止めたいときは環境変数 LOADOUT_GUARD=deny。
LOADOUT.md がなければ何もしない。"""
import json, os, re, sys, pathlib


def find_loadout(start: pathlib.Path):
    p = start
    for _ in range(5):
        f = p / "LOADOUT.md"
        if f.is_file():
            return f
        if p.parent == p:
            break
        p = p.parent
    return None


def parse(text: str):
    out = {"builder": None, "checker": None, "excluded": []}
    for line in text.splitlines():
        line = line.strip()
        m = re.match(r"^(作る用|builder)\s*[:：]\s*([\w.@/-]+)", line, re.I)
        if m:
            out["builder"] = m.group(2)
        m = re.match(r"^(点検用|checker)\s*[:：]\s*([\w.@/-]+)", line, re.I)
        if m:
            out["checker"] = m.group(2)
        m = re.match(r"^(読まない|do not load|excluded)\s*[:：]\s*(.+)$", line, re.I)
        if m:
            out["excluded"] = [s.strip() for s in re.split(r"[、,\s]+", re.sub(r"[（(].*$", "", m.group(2))) if s.strip() and s.strip() != "なし"]
    return out


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return
    if data.get("tool_name") != "Skill":
        return
    skill = str((data.get("tool_input") or {}).get("skill", "")).split(":")[-1]
    cwd = pathlib.Path(data.get("cwd") or os.getcwd())
    f = find_loadout(cwd)
    if not f or not skill:
        return
    lo = parse(f.read_text(encoding="utf-8", errors="ignore"))
    if skill in lo["excluded"]:
        msg = (f"[LOADOUT] {skill} は {f} で「読まない」に入っています"
               f"（作る用: {lo['builder'] or '未定'}、点検用: {lo['checker'] or '未定'}）。"
               "読むなら、どの軸を直すためかを1行書いてから読む。全体を読まず、その軸の節だけにする。")
        if os.environ.get("LOADOUT_GUARD") == "deny":
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                              "permissionDecision": "deny", "permissionDecisionReason": msg}}, ensure_ascii=False))
        else:
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                              "additionalContext": msg}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
