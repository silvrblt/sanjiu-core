#!/usr/bin/env python3
"""type_eval.py — 类型专项测评 runner（2026-09-04 排期执行）
8 基准模型 × 同题直连 API，输出存 evidence/type-eval/，供验收脚本与后续双盲评分。
用法：python3 type_eval.py <bench|test> <code_gen|text_gen>
"""
import json
import os
import time
import urllib.request

MODELS = {
    "deepseek-v4-flash": {"key": "DEEPSEEK_API_KEY", "url": "https://api.deepseek.com/v1/chat/completions"},
    "deepseek-v4-pro": {"key": "DEEPSEEK_API_KEY", "url": "https://api.deepseek.com/v1/chat/completions"},
    "glm-5.3": {"key": "GLM_API_KEY", "url": "https://open.bigmodel.cn/api/paas/v4/chat/completions"},
    "hy3": {"key": "HUNYUAN_API_KEY", "url": "https://tokenhub.tencentmaas.com/v1/chat/completions"},
    "minimax-m3": {"key": "MINIMAX_API_KEY", "url": "https://api.minimax.chat/v1/text/chatcompletion_v2"},
    "doubao-seed-2-1-turbo-260628": {"key": "ARK_API_KEY", "url": "https://ark.cn-beijing.volces.com/api/v3/chat/completions", "seat": "doubao-2.1-turbo"},
    "kimi-k2.7-code": {"key": "MOONSHOT_API_KEY", "url": "https://api.moonshot.cn/v1/chat/completions"},
    "qwen3.8-max": {"key": "QWEN_API_KEY", "url": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"},
}

TASKS = {
    "code_gen": "用 Python 写一个函数 parse_config(text)：解析 KEY=VALUE 配置文本为 dict，支持 # 注释行与带引号的值（'x' 或 \"x\" 要去掉引号），忽略空行。≤60 行，只输出完整可运行的 Python 代码，不要解释。",
    "text_gen": "写一份 200-250 字的律所经营中后台产品介绍：面向中小律所，突出案件管理、财务一体化、数据看板三个能力，强调数据资产沉淀与经营决策提效。只输出正文，不要标题。",
}


def call(model, prompt, out_dir):
    cfg = MODELS[model]
    key = os.environ.get(cfg["key"], "")
    if not key:
        print(f"  {model}: 缺 {cfg['key']}，跳过")
        return
    body = {"model": model, "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 3000, "stream": False}
    try:
        req = urllib.request.Request(cfg["url"], data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json",
                                              "Authorization": f"Bearer {key}"})
        t0 = time.time()
        r = json.loads(urllib.request.urlopen(req, timeout=300).read())
        text = r["choices"][0]["message"]["content"]
        u = r.get("usage", {})
        out = os.path.join(out_dir, f"{model}.txt")
        open(out, "w").write(text)
        print(f"  {model}: OK {time.time()-t0:.0f}s out={u.get('completion_tokens',0)} tok → {out}")
        return {"model": model, "seconds": round(time.time()-t0), "out_tokens": u.get("completion_tokens", 0)}
    except Exception as e:
        print(f"  {model}: FAIL {str(e)[:100]}")
        return None


def main():
    task = sys_argv_task()
    models = list(MODELS.keys())
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs", "evidence", "type-eval", task)
    os.makedirs(out_dir, exist_ok=True)
    print(f"=== {task} × {len(models)} 模型 ===")
    results = []
    for m in models:
        r = call(m, TASKS[task], out_dir)
        if r:
            results.append(r)
    meta = {"task": task, "date": "2026-09-04", "prompt": TASKS[task], "results": results}
    json.dump(meta, open(os.path.join(out_dir, "_meta.json"), "w"), ensure_ascii=False, indent=1)
    print(f"完成 {len(results)}/{len(models)}")


def sys_argv_task():
    import sys
    return sys.argv[1] if len(sys.argv) > 1 else "code_gen"


if __name__ == "__main__":
    main()
