#!/usr/bin/env python3
"""type_eval_blind.py — 类型测评双盲评分（kimi-k2.7-code 主评，排期二.2）
流程（盲测纪律全套）：①承办锁存解密表（先存 mapping 再评分，防后改）→ ②逐份去标识产出调 kimi 评分
→ ③解密算均分 → 达标复核 = 自动验收 PASS 且 双盲均分 ≥6.0（<6.0 自动回改 yaml types，由承办执行）
范围（主观质量维度）：text_gen / text_understand / code_gen_hard（产出质量）；客观题（data_analysis/code_audit
锚定判定）以自动验收为终判，视觉（ui_design）走渲染双盲另册。
用法：TYPE_EVAL_EVIDENCE=<根> python3 type_eval_blind.py [text_gen text_understand code_gen_hard]
"""
import json
import os
import random
import re
import sys
import time
import urllib.request

OUT = os.environ.get("TYPE_EVAL_EVIDENCE", "/Users/sun/codex-workspace/docs/evidence/type-eval")
TASKS = sys.argv[1:] or ["text_gen", "text_understand", "code_gen_hard"]

RUBRICS = {
    "text_gen": (
        "评分标准（0-10，按三项加权合计）："
        "①内容覆盖 0-4：律所经营中后台定位清晰，覆盖案件管理/财务一体化/数据看板能力，含数据资产沉淀与经营决策提效；"
        "②表达质量 0-3：通顺专业、无空泛套话与堆砌；③信息密度 0-3：层次清楚、无冗余铺垫。"),
    "text_understand": (
        "评分标准（0-10）："
        "①要点忠实 0-4：无虚构、无对协议条款的错读；②关键事实覆盖 0-3：金额/比例/日期/解约/仲裁等要素齐全；"
        "③要点质量 0-3：精炼成条（每条≤30字）、无大段照抄、重点不漏。"),
    "code_gen_hard": (
        "评分标准（0-10）："
        "①题面符合 0-4：cond 与算术表达式为自研解析求值（禁止 eval/exec 与直接依赖 ast 等现成解析），缺失字段短路不抛异常；"
        "②健壮性 0-3：边界处理完备、无隐藏崩溃路径；③简洁可读 0-3：无冗余分支与死代码，命名清楚。"),
    "code_gen": (
        "评分标准（0-10）："
        "①功能实现质量 0-4：parse_config 逻辑正确且覆盖注释/引号/空行要求；"
        "②代码健壮与简洁 0-3：无多余分支、类型处理稳；③可读与规范 0-3：命名清楚、结构自然、无累赘解释。"),
}

BLIND_DIR = os.path.join(OUT, "blind")


def api_call(prompt, model="kimi-k2.7-code", max_tokens=None):
    import os as _os
    max_tokens = max_tokens or int(_os.environ.get("TYPE_EVAL_MAX", "6000"))
    key = os.environ.get("MOONSHOT_API_KEY", "")
    body = {"model": model, "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens, "stream": False}
    req = urllib.request.Request("https://api.moonshot.cn/v1/chat/completions",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json",
                                          "Authorization": f"Bearer {key}"})
    r = json.loads(urllib.request.urlopen(req, timeout=480).read())
    msg = r["choices"][0]["message"]
    text = msg.get("content") or ""
    if not text.strip() and msg.get("reasoning_content"):
        raise RuntimeError("content 空（reasoning 吃满 max_tokens）")
    return text, r.get("usage", {})


def collect(task):
    """产出清单（跳过 prompt.txt 与截断/空文件）。"""
    d = os.path.join(OUT, task)
    files = []
    for f in sorted(os.listdir(d)):
        if not f.endswith(".txt") or f.startswith("prompt"):
            continue
        text = open(os.path.join(d, f), encoding="utf-8").read().strip()
        if len(text) < 40:
            continue  # 空/截断产出不盲评（自动验收已判）
        files.append((f[:-4], text))
    return files


CODE_GEN_SIMPLE_PROMPT = (
    "用 Python 写一个函数 parse_config(text)：解析 KEY=VALUE 配置文本为 dict，"
    "支持 # 注释行与带引号的值（'x' 或 \"x\" 要去掉引号），忽略空行。"
    "≤60 行，只输出完整可运行的 Python 代码，不要解释。")


def task_prompt(task):
    p = os.path.join(OUT, task, "prompt.txt")
    if os.path.exists(p):
        return open(p, encoding="utf-8").read()
    if task == "code_gen":
        return CODE_GEN_SIMPLE_PROMPT
    return json.load(open(os.path.join(OUT, task, "_meta.json"), encoding="utf-8"))["prompt"]


def main():
    os.makedirs(BLIND_DIR, exist_ok=True)
    decrypt_path = os.path.join(BLIND_DIR, "解密表-承办锁存.json")
    lock = json.load(open(decrypt_path, encoding="utf-8")) if os.path.exists(decrypt_path) else {}
    for task in TASKS:
        files = collect(task)
        scores_path = os.path.join(BLIND_DIR, f"{task}_blind.json")
        scores = json.load(open(scores_path, encoding="utf-8")) if os.path.exists(scores_path) else {}
        todo_files = [(m, t) for m, t in files if m not in {v["model"] for v in scores.values()} or not all(
            v["score"] is not None for v in scores.values() if v["model"] == m)]
        print(f"=== {task}: {len(files)} 份产出，待评 {len(todo_files)} ===", flush=True)
        # ①锁存：已锁存则复用（防解密错位）；否则新建随机匿名映射先落盘再评分
        if task in lock:
            mapping = lock[task]
        else:
            rnd = random.Random(20260904 + sum(map(ord, task)))
            labels = [f"产出-{chr(65+i)}" for i in range(len(files))]
            rnd.shuffle(labels)
            mapping = dict(zip(labels, [m for m, _ in files]))
            lock[task] = mapping
            json.dump(lock, open(decrypt_path, "w"), ensure_ascii=False, indent=1)
        label_of = {m: l for l, m in mapping.items()}
        todo_files = [(label_of[m], m, t) for m, t in todo_files if m in label_of]
        tprompt = task_prompt(task)
        for label, model, text in sorted(todo_files):
            if scores.get(label, {}).get("score") is not None:
                continue
            prompt = ("你是中立质量评审。以下是【任务】与【一份匿名产出】，请按评分标准打分。"
                      "只输出一行：分数: <数字>/10，再给一行依据（≤60字），不要其他内容。\n"
                      f"【任务】\n{tprompt}\n\n"
                      f"【评分标准】\n{RUBRICS[task]}\n\n【匿名产出】\n{text}\n")
            try:
                resp, usage = api_call(prompt)
                m = re.search(r"分数\s*[:：]\s*(\d+(?:\.\d+)?)", resp)
                score = float(m.group(1)) if m else None
                print(f"  {label}({model}): {score} | {resp.strip()[:80]}", flush=True)
                scores[label] = {"model": model, "score": score, "raw": resp[:200],
                                 "in": usage.get("prompt_tokens", 0), "out": usage.get("completion_tokens", 0)}
            except Exception as e:
                print(f"  {label}: FAIL {str(e)[:80]}", flush=True)
                scores[label] = {"model": model, "score": None, "raw": f"调用失败 {e}"[:200]}
        json.dump(scores, open(scores_path, "w"), ensure_ascii=False, indent=1)
    print("完成 → evidence/type-eval/blind/")


if __name__ == "__main__":
    main()
