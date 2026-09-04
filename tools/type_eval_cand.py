#!/usr/bin/env python3
"""type_eval_cand.py — 类型测评候选层抽测（排期执行顺序 ②）
抽测：qwen3-max × text_gen（第一批题面复用）、kimi-k2.6 × text_understand（第二批题面复用）。
产出：evidence/cand_spot/<task>/<model>.txt + _meta.json；逐调用 cost-log 记账。
用法：TYPE_EVAL_EVIDENCE=<绝对路径> python3 type_eval_cand.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import type_eval2 as te  # noqa: E402  复用 MODELS/CANDIDATES/call/cost_log 基建

OUT = os.environ["TYPE_EVAL_EVIDENCE"]
SPOTS = {
    # (候选 API ID, 任务类型, 题面来源任务)
    "qwen3-max": ("text_gen", "text_gen"),
    "kimi-k2.6": ("text_understand", "text_understand"),
}


def load_prompt(task, src_task):
    """题面：本批 TASKS 优先；text_gen 复用第一批 _meta.json 内嵌 prompt。"""
    if task in te.TASKS:
        return te.TASKS[task]
    meta = json.load(open(os.path.join(OUT, src_task, "_meta.json"), encoding="utf-8"))
    return meta["prompt"]


def cost_log(model, tin, tout, task, note=""):
    label = {"hy3": "hunyuan-hy3"}.get(model, model)
    log = os.environ.get("TYPE_EVAL_COSTLOG",
                         "/Users/sun/codex-workspace/01_projects/cost-opt/tools/cost-log.sh")
    os.system(f'"{log}" seat=类型测评-候选 model={label} in={tin} out={tout} real '
              f'task=type-eval-{task} machine=macmini seat_class=lead note="{note}" >/dev/null 2>&1')


def main():
    for model, (task, src_task) in SPOTS.items():
        prompt = load_prompt(task, src_task)
        out_dir = os.path.join(OUT, "cand_spot", task)
        os.makedirs(out_dir, exist_ok=True)
        open(os.path.join(out_dir, "prompt.txt"), "w").write(prompt)
        print(f"=== 候选抽测 {model} × {task} ===", flush=True)
        r = te.call(model, task, prompt, out_dir, cost_log)
        if r:
            json.dump({"task": task, "date": "2026-09-04", "round": "候选抽测",
                       "prompt_file": "prompt.txt", "results": [r]},
                      open(os.path.join(out_dir, f"_meta_{model}.json"), "w"), ensure_ascii=False, indent=1)
            print(f"{model} OK in={r['in_tokens']} out={r['out_tokens']}")


if __name__ == "__main__":
    main()
