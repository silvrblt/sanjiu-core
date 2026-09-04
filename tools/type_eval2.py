#!/usr/bin/env python3
"""type_eval2.py — 类型专项测评第二批 runner（2026-09-04 排期执行）
基准层 8 模型 × 5 任务直连 API（code_gen_hard/data_analysis/text_understand/code_audit/ui_design），
输出存 evidence/type-eval/<task>/，逐调用 cost-log 记账。
用法：
  TYPE_EVAL_EVIDENCE=<abs路径> python3 type_eval2.py            # 跑全部 5 任务 × 8 基准模型
  TYPE_EVAL_EVIDENCE=<abs路径> python3 type_eval2.py --only qwen3-max kimi-k2.6  # 指定模型（候选抽测）
教训（第一批）：reasoning 模型 max_tokens 3000 被思考吃满致 content 空——本批统一 8000，
content 仍空且 reasoning_content 非空 → 自动以 16000 重跑一次（同批人工修复逻辑内建）。
"""
import json
import os
import sys
import time
import threading
import urllib.request
from concurrent.futures import ThreadPoolExecutor

# 模型 → (API 模型 ID, key 环境变量, 端点)；与第一批 type_eval.py 同构
MODELS = {
    "deepseek-v4-flash": ("deepseek-v4-flash", "DEEPSEEK_API_KEY", "https://api.deepseek.com/v1/chat/completions"),
    "deepseek-v4-pro": ("deepseek-v4-pro", "DEEPSEEK_API_KEY", "https://api.deepseek.com/v1/chat/completions"),
    "hy3": ("hy3", "HUNYUAN_API_KEY", "https://tokenhub.tencentmaas.com/v1/chat/completions"),
    "minimax-m3": ("minimax-m3", "MINIMAX_API_KEY", "https://api.minimax.chat/v1/text/chatcompletion_v2"),
    "doubao-seed-2-1-turbo-260628": ("doubao-seed-2-1-turbo-260628", "ARK_API_KEY", "https://ark.cn-beijing.volces.com/api/v3/chat/completions"),
    "kimi-k2.7-code": ("kimi-k2.7-code", "MOONSHOT_API_KEY", "https://api.moonshot.cn/v1/chat/completions"),
    "glm-5.3": ("glm-5.3", "GLM_API_KEY", "https://open.bigmodel.cn/api/paas/v4/chat/completions"),
    "qwen3.8-max": ("qwen3.8-max", "QWEN_API_KEY", "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"),
}
# 候选层抽测（价格核验 v3 全 ✓ verbatim；API ID 同厂商官方命名，404 则探明记录不硬猜）
CANDIDATES = {
    "qwen3-max": ("qwen3-max", "QWEN_API_KEY", "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"),
    "kimi-k2.6": ("kimi-k2.6", "MOONSHOT_API_KEY", "https://api.moonshot.cn/v1/chat/completions"),
}

BENCH = [
    "deepseek-v4-flash", "deepseek-v4-pro", "hy3", "minimax-m3",
    "doubao-seed-2-1-turbo-260628", "kimi-k2.7-code", "glm-5.3", "qwen3.8-max",
]

_CSV = """date,category,amount,customer
2025-06-03,咨询费,12000,恒信科技
2025-06-15,咨询费,8500,恒信科技
2025-06-20,差旅费,3200,明川置业
2025-06-28,办公费,1450,内部
2025-07-02,咨询费,9600,拓维数据
2025-07-10,咨询费,15000,恒信科技
2025-07-18,差旅费,5600,明川置业
2025-07-25,办公费,780,内部
2025-07-30,咨询费,-300,拓维数据
2025-08-05,咨询费,13200,恒信科技
2025-08-12,咨询费,6800,拓维数据
2025-08-19,差旅费,4100,明川置业
2025-08-26,办公费,2200,内部
2025-08-29,咨询费,9000,恒信科技"""

_CODE_AUDIT_SRC = '''import sqlite3, csv

def submit_fee(db_conn, user, fee):
    """律所后台：律师为名下客户登记一笔费用（金额单位：元）。"""
    if fee["amount"] < 0 or fee["amount"] > 1000000:
        raise ValueError("金额超出范围")
    sql = "INSERT INTO fees (customer_id, amount, note) VALUES (%s, %s, '%s')" % (fee["customer_id"], fee["amount"], fee["note"])
    db_conn.execute(sql)

def approve_fee(db_conn, user, fee_id, approve):
    """审批草稿费用：approve=True 通过，False 退回。"""
    row = db_conn.execute("SELECT * FROM drafts WHERE id = ?", (fee_id,)).fetchone()
    if row is None:
        return "草稿不存在"
    db_conn.execute("UPDATE drafts SET status = ? WHERE id = ?", ("approved" if approve else "rejected", fee_id))
    db_conn.commit()
    return "已处理"

def adjust_balance(db_conn, customer_id, delta):
    """调整客户预存余额（含优惠抵扣等场景）。"""
    row = db_conn.execute("SELECT balance FROM balances WHERE customer_id = ?", (customer_id,)).fetchone()
    balance = row["balance"]
    if balance + delta < 0:
        return "余额不足"
    if balance == 0.0 or delta == 0.0:
        return "无需调整"
    db_conn.execute("UPDATE balances SET balance = ? WHERE customer_id = ?", (balance + delta, customer_id))
    db_conn.commit()
    return "已调整"

def export_fees(db_conn, out_path):
    """导出全部费用明细到 CSV（对账用）。"""
    rows = db_conn.execute("SELECT * FROM fees")
    f = open(out_path, "w", encoding="utf-8")
    w = csv.writer(f)
    w.writerow(["id", "customer_id", "amount", "note", "created_at"])
    for r in rows:
        w.writerow(list(r))

def batch_import(db_conn, records):
    """批量导入费用记录；单条失败不应中断整批（记录日志后继续）。"""
    for rec in records:
        try:
            submit_fee(db_conn, {"customer_id": -1}, rec)
        except Exception:
            pass
    db_conn.commit()
    return "导入完成，失败已跳过"'''

TASKS = {
    "code_gen_hard": (
        "用 Python 实现函数 evaluate_rules(customer, rules)，做条件规则求值（律所客户分层积分场景）。\n"
        "customer 为 dict，如 {\"spend\": 12800, \"type\": \"corporate\", \"months\": 6, \"region\": \"east\"}；"
        "字段值只可能是 int/float/str，也可能缺失。\n"
        "rules 为 list[dict]，每项 {\"id\": ..., \"cond\": str, \"action\": dict}。\n"
        "cond 是条件表达式字符串，语法：\n"
        "  比较：==  !=  >  >=  <  <=，操作数 = 字段名 | 数字字面量（含小数）| 单引号或双引号字符串字面量\n"
        "  逻辑：and or not，支持括号；优先级：not > and > or\n"
        "  约束：customer 中缺失的字段在比较中一律按 False 处理（整条 cond 短路为 False，不得抛异常）\n"
        "action 为 {\"points\": 数值字面量 或 字段算术表达式}；字段算术表达式仅支持 + - * / 与括号、操作数为字段名或数字，如 \"spend/70\"，求值后向下取整为 int。\n"
        "语义：按 rules 顺序返回第一条 cond 为真的 action 求值结果 dict {\"points\": int}；全部不命中返回 None。\n"
        "禁止使用 eval/exec/动态 import；cond 与算术表达式必须自己解析求值，不得硬编码字段名集合。\n"
        "≤120 行。只输出完整可运行的 Python 代码（函数定义即可），不要解释，不要 markdown 围栏。"
    ),
    "data_analysis": (
        "以下是某律所 2025 年 6-8 月费用账单（CSV，表头 date,category,amount,customer，金额单位元）：\n"
        + _CSV +
        "\n\n只做算术，请回答 5 个问题，输出格式为每行一个：Q<编号> <数字>（如 Q1 100），不要任何解释、不要逗号分隔符、不要千分位：\n"
        "Q1：全部账单金额合计（含退款负值）？\n"
        "Q2：金额最大的类别，该类别合计金额？\n"
        "Q3：8 月份咨询费合计金额？\n"
        "Q4：客户「恒信科技」全部账单合计金额？\n"
        "Q5：单笔金额严格大于 8000 的账单有几笔？"
    ),
    "text_understand": (
        "阅读以下协议条款节选，用不超过 8 条要点概括（每条 ≤30 字，只列要点不要标题与解释）：\n"
        "----\n"
        "《律所经营管理系统采购与服务协议》（节选）\n"
        "第二条 费用与支付：合同总价 186,000 元，分三期支付——合同签订后 10 个工作日内支付 40%，"
        "系统上线验收通过后支付 50%，免费维护期届满后支付尾款 10%。\n"
        "第三条 交付与违约责任：系统应于 2025 年 12 月 31 日前完成上线；每逾期一日，供应商应按合同总价的 0.1% 向律所支付违约金；"
        "累计逾期超过 60 日的，律所有权单方解除合同并要求退还已付全部费用。\n"
        "第四条 数据与知识产权：使用系统过程中沉淀的全部业务数据（含客户信息、案件卷宗、财务记录）归律所所有，"
        "供应商不得用于模型训练、不得提供给任何第三方，合同终止后 30 日内应完整返还并删除本地副本。\n"
        "第五条 保密：双方对合作中知悉的对方商业秘密保密，保密义务自合同生效之日起持续 5 年。\n"
        "第六条 维护与升级：自上线验收通过之日起提供 12 个月免费维护；维护期后的续费服务按年计费，"
        "续费首年费用为合同总价的 12%，此后每年涨幅不超过 10%。\n"
        "第七条 争议解决：因本合同发生的争议，提交深圳国际仲裁院仲裁，仲裁裁决为终局，对双方均有约束力。\n"
        "----\n"
        "注意：要点须覆盖金额/日期/比例等关键事实；每条要独立成行。"
    ),
    "code_audit": (
        "以下是一段律所后台费用管理模块的 Python 代码，存在 5 个真实缺陷（安全/正确性/健壮性维度）。"
        "请逐条列出你发现的问题，输出格式为每行一条：<问题所在行号> <严重度:高/中/低> <问题简述与修复建议>，最多输出 10 条：\n"
        "----\n" + _CODE_AUDIT_SRC + "\n----\n"
        "只输出问题清单本身，不要复述代码。"
    ),
    "ui_design": (
        "为律所经营中后台设计一个「经营看板」页面，输出单一 HTML 文件（完整 <!DOCTYPE html>，样式用内联 <style>，"
        "脚本可用少量内联 <script>，禁止任何外部 CDN/资源链接/图片）。\n"
        "页面必须包含：\n"
        "① 左侧深色侧栏导航，含 品牌名「律所经营中后台」与 4 个导航项：案件管理/客户管理/财务管理/系统设置；\n"
        "② 顶部为页面标题「经营看板」与当前日期；\n"
        "③ 4 个 KPI 指标卡：本季创收（¥1,286,400，环比 +12.6%）、在办案件（186 件）、客户总数（2,340）、回款率（87.3%，环比 +3.1%）；\n"
        "④ 一个「近 12 个月创收趋势」图（用内联 SVG/Canvas/纯 CSS 柱条均可，必须标注 1月-12月 月份轴）；\n"
        "⑤ 一个「案件状态分布」图（环形或横向条形均可，内联实现，含 进行中/已归档/待立案/已结案 4 类）；\n"
        "⑥ 一张「最近案件」明细表，表头含 案号/客户/案件类型/承办律师/标的额/状态，至少 6 行数据。\n"
        "只输出 HTML 代码本身，不要解释。"
    ),
}


def call_once(api_model, key_env, url, prompt, max_tokens):
    key = os.environ.get(key_env, "")
    if not key:
        return None, "缺密钥"
    body = {"model": api_model, "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens, "stream": False}
    try:
        req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json",
                                              "Authorization": f"Bearer {key}"})
        t0 = time.time()
        r = json.loads(urllib.request.urlopen(req, timeout=int(os.environ.get("TYPE_EVAL_TIMEOUT", "600"))).read())
    except Exception as e:
        return None, f"调用异常: {type(e).__name__} {str(e)[:120]}"
    msg = r["choices"][0]["message"]
    text = msg.get("content") or ""
    u = r.get("usage", {})
    return {"text": text, "sec": round(time.time() - t0),
            "usage": {"in": u.get("prompt_tokens", 0), "out": u.get("completion_tokens", 0),
                      "reasoning": u.get("reasoning_tokens", u.get("completion_tokens_details", {}).get("reasoning_tokens", 0)),
                      "rc_content": bool(msg.get("reasoning_content"))}}, None


def call(model, task, prompt, out_dir, cost_log):
    api_model, key_env, url = MODELS.get(model) or CANDIDATES.get(model)
    ok, last_err = None, ""
    chain = tuple(int(x) for x in os.environ.get("TYPE_EVAL_MAX", "8000,16000,32000").split(","))
    for attempt in chain:
        res, err = call_once(api_model, key_env, url, prompt, attempt)
        if err:
            last_err = err
            continue
        if res["text"].strip():
            ok = res
            break
        if not res["usage"]["rc_content"]:  # 无 reasoning_content 的空输出 = 真失败，不重试放大
            ok = res
            break
        last_err = f"content 空（reasoning {res['usage']['reasoning']} tok 吃满 {attempt}）→ 放大重试"
    if ok is None:
        print(f"  {model}: FAIL {last_err}")
        return None
    open(os.path.join(out_dir, f"{model}.txt"), "w").write(ok["text"])
    u = ok["usage"]
    print(f"  {model}: OK {ok['sec']}s in={u['in']} out={u['out']} reasoning={u['reasoning']} → {model}.txt")
    cost_log(model, u["in"], u["out"], task, note=last_err if "重试" in last_err else f"{task} 测评")
    return {"model": model, "seconds": ok["sec"], "in_tokens": u["in"], "out_tokens": u["out"],
            "reasoning_tokens": u["reasoning"]}


def sha1_of(text):
    import hashlib
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    only_models = None
    if "--only" in sys.argv:
        i = sys.argv.index("--only")
        only_models = sys.argv[i + 1:]
    out_root = os.environ.get("TYPE_EVAL_EVIDENCE")
    if not out_root:
        print("需 TYPE_EVAL_EVIDENCE=<证据目录绝对路径>（统一 canonical: /Users/sun/codex-workspace/docs/evidence/type-eval）")
        sys.exit(2)
    cost_log_path = os.environ.get("TYPE_EVAL_COSTLOG",
                                   "/Users/sun/codex-workspace/01_projects/cost-opt/tools/cost-log.sh")
    lock = threading.Lock()

    def cost_log(model, tin, tout, task, note=""):
        label = {"hy3": "hunyuan-hy3"}.get(model, model)
        cmd = f'"{cost_log_path}" seat=类型测评 model={label} in={tin} out={tout} real ' \
              f'task=type-eval-{task} machine=macmini seat_class=lead note="{note}" >/dev/null 2>&1'
        with lock:
            os.system(cmd)

    tasks = args or list(TASKS.keys())
    models = only_models or BENCH
    print(f"=== 类型测评第二批 {tasks} × {models} ===")
    for task in tasks:
        prompt = TASKS[task]
        out_dir = os.path.join(out_root, task)
        os.makedirs(out_dir, exist_ok=True)
        prompt_sha = sha1_of(prompt)
        sha_file = os.path.join(out_dir, ".prompt.sha")
        done = {}
        if os.path.exists(sha_file) and open(sha_file).read().strip() == prompt_sha:
            done = {f[:-4] for f in os.listdir(out_dir) if f.endswith(".txt")}
        open(sha_file, "w").write(prompt_sha)
        open(os.path.join(out_dir, "prompt.txt"), "w").write(prompt)
        todo = [m for m in models if m not in done]
        print(f"任务 {task}：{len(models)} 模型中待跑 {len(todo)}（已完成跳过 {len(models)-len(todo)}）", flush=True)
        if not todo:
            continue
        results = []
        with ThreadPoolExecutor(max_workers=4) as ex:
            futs = {ex.submit(call, m, task, prompt, out_dir, cost_log): m for m in todo}
            for f in futs:
                r = f.result()
                if r:
                    results.append(r)
        meta = {"task": task, "date": "2026-09-04", "round": "第二批",
                "models": models, "prompt_file": "prompt.txt", "results": results}
        json.dump(meta, open(os.path.join(out_dir, "_meta.json"), "w"), ensure_ascii=False, indent=1)
        print(f"任务 {task} 完成 {len(results)}/{len(todo)}", flush=True)


if __name__ == "__main__":
    main()
