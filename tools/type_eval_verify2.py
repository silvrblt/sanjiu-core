#!/usr/bin/env python3
"""type_eval_verify2.py — 类型测评第二批自动验收（黄金样例/断言；达标 = 本脚本 PASS）
用法：python3 type_eval_verify2.py <evidence根> [task ...]   （默认 5 任务全验收）
产出：evidence/<task>_结果.md；打印验收明细。视觉品质（ui_design）双盲评分后置（排期二.2）。
"""
import ast
import csv
import io
import json
import os
import re
import subprocess
import sys
import tempfile

OUT_ROOT = sys.argv[1] if len(sys.argv) > 1 else "/Users/sun/codex-workspace/docs/evidence/type-eval"
TASKS = sys.argv[2:] or ["code_gen_hard", "data_analysis", "text_understand", "code_audit", "ui_design"]

MODEL_LABEL = {  # 展示名归一（evidence 文件名即 API 模型 ID）
    "doubao-seed-2-1-turbo-260628": "doubao-2.1-turbo", "hunyuan-hy3": "hy3"}


def strip_fences(text):
    text = re.sub(r"^```[a-zA-Z]*\s*", "", text.strip())
    return re.sub(r"\s*```$", "", text)


# ---------------- code_gen_hard：AST 合规 + 8 断言子进程执行 ----------------
CODEGEN_TEST = '''
_cases = []
def _chk(name, got, exp):
    _cases.append((name, got, exp))
    print(("PASS" if got == exp else "FAIL") + " " + name + " got=" + repr(got) + " exp=" + repr(exp))

c1 = {"spend": 12800, "type": "corporate", "months": 6, "region": "east"}
r1 = [{"id": 1, "cond": 'type == "corporate" and spend > 10000', "action": {"points": 100}},
      {"id": 2, "cond": 'type == "corporate"', "action": {"points": 50}}]
_chk("and-首条命中", evaluate_rules(c1, r1)["points"], 100)
_chk("and-首条未中取次条", evaluate_rules({"spend": 8000, "type": "corporate"}, r1)["points"], 50)
r2 = [{"id": 1, "cond": 'not (months < 3 or region == "west")', "action": {"points": "spend/70"}},
      {"id": 2, "cond": "True", "action": {"points": 1}}]
_chk("not-括号-字段算术下取整", evaluate_rules(c1, r2)["points"], 182)
r3 = [{"id": 1, "cond": 'region > "c"', "action": {"points": 7}}]
_chk("字符串字典序大于", evaluate_rules(c1, r3)["points"], 7)
r4 = [{"id": 1, "cond": "unknown_field == 5", "action": {"points": 9}}]
_chk("未知字段不抛错且为False", evaluate_rules(c1, r4), None)
r5 = [{"id": 1, "cond": 'months >= 6 and spend <= 20000 and type != "individual"', "action": {"points": 200}}]
_chk("比较运算符组合", evaluate_rules(c1, r5)["points"], 200)
r6 = [{"id": 1, "cond": 'type == "individual"', "action": {"points": 5}},
      {"id": 2, "cond": "spend < 1000", "action": {"points": 1}}]
_chk("缺失字段短路下一规则", evaluate_rules({"spend": 500}, r6)["points"], 1)
r7 = [{"id": 1, "cond": "spend >= 12800 and months == 6", "action": {"points": 3.7}},
      {"id": 2, "cond": "spend >= 12800.0", "action": {"points": 4}}]
_chk("浮点字面量点数取整", evaluate_rules(c1, r7)["points"], 3)
r8 = [{"id": 1, "cond": "not not (spend > 100)", "action": {"points": "100 - 40 + 2*3"}}]
_chk("双重not与算术优先级", evaluate_rules(c1, r8)["points"], 66)
'''


def _compliant(code):
    """合规闸：白名单 stdlib import；AST 扫描禁用内建调用（eval/exec/open/input/compile/__import__）。
    文本扫描弃用（注释/字符串提及会误伤——2026-09-04 实测 kimi 注释误杀教训）。"""
    ALLOWED_IMPORTS = {"typing", "dataclasses", "math", "re", "ast", "operator",
                       "itertools", "functools", "collections"}
    FORBIDDEN_CALLS = {"eval", "exec", "open", "input", "compile", "__import__"}
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return False, f"语法错误: {e}"
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = {a.name.split(".")[0] for a in node.names} if isinstance(node, ast.Import) \
                else {node.module.split(".")[0]} if node.module else set()
            if not names <= ALLOWED_IMPORTS:
                return False, f"违规 import: {names}"
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id in FORBIDDEN_CALLS:
            return False, f"禁用内建调用: {node.func.id}("
    return True, ""


def verify_code_gen_hard(path):
    total_asserts = len(re.findall(r"\n_chk\(", CODEGEN_TEST))  # 断言总数（仅调用行，不含 def）
    out = {}
    for f in sorted(os.listdir(path)):
        if not f.endswith(".txt") or f.startswith("prompt"):
            continue
        model = f[:-4]
        code = strip_fences(open(os.path.join(path, f), encoding="utf-8").read())
        ok, why = _compliant(code)
        if not ok:
            out[model] = (0, why)
            continue
        test = code + "\n" + CODEGEN_TEST
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as tf:
            tf.write(test)
            tmp = tf.name
        try:
            r = subprocess.run(["python3", tmp], capture_output=True, text=True, timeout=30)
            lines = [l for l in r.stdout.splitlines() if l.startswith(("PASS", "FAIL"))]
            passed = sum(1 for l in lines if l.startswith("PASS"))
            failed = [l[5:] for l in lines if l.startswith("FAIL")]
            out[model] = (passed, f"{passed}/{total_asserts} 通过" + (f"；失败: {'; '.join(failed)}" if failed else "")
                          + (f"；stderr: {r.stderr[:120]}" if r.returncode and not lines else ""))
        except subprocess.TimeoutExpired:
            out[model] = (0, "执行超时")
        finally:
            os.unlink(tmp)
    return out, total_asserts, total_asserts


# ---------------- data_analysis：黄金值（由嵌入 CSV 现算，自洽） ----------------
def _golden():
    prompt = open(os.path.join(OUT_ROOT, "data_analysis", "prompt.txt"), encoding="utf-8").read()
    m = re.search(r"(date,category,amount,customer\n.*?)\n\n只做算术", prompt, re.S)
    rows = list(csv.DictReader(io.StringIO(m.group(1))))
    rows = [{**r, "amount": float(r["amount"]), "date": r["date"]} for r in rows]
    cats = {}
    for r in rows:
        cats[r["category"]] = cats.get(r["category"], 0) + r["amount"]
    top = max(cats, key=cats.get)
    return [sum(r["amount"] for r in rows),
            round(max(cats.values()), 2),
            round(sum(r["amount"] for r in rows if r["date"].startswith("2025-08") and r["category"] == "咨询费"), 2),
            round(sum(r["amount"] for r in rows if r["customer"] == "恒信科技"), 2),
            sum(1 for r in rows if r["amount"] > 8000)]


def verify_data_analysis(path):
    gold = _golden()
    out = {}
    for f in sorted(os.listdir(path)):
        if not f.endswith(".txt") or f.startswith("prompt"):
            continue
        model = f[:-4]
        text = open(os.path.join(path, f), encoding="utf-8").read()
        ans = {}
        for num in re.finditer(r"Q(\d)\s*[:：]?\s*(-?\d+(?:\.\d+)?)", text):
            ans[int(num.group(1))] = float(num.group(2))
        hits = 0
        detail = []
        for i, g in enumerate(gold, 1):
            a = ans.get(i)
            ok = a is not None and abs(a - g) <= max(0.005 * abs(g), 0.01)
            hits += ok
            detail.append(f"Q{i}={'✓' if ok else '✗'}(期望{g}" + (f", 得{a})" if a is not None else "，未检出)"))
        out[model] = (hits, "5/5 ✓" if hits == 5 else f"{hits}/5；" + " ".join(detail))
    return out, 5, 5


# ---------------- text_understand：黄金要点覆盖（7 项，命中 ≥5 达标） ----------------
TU_ITEMS = {
    1: ["186,000", "186000", "18.6万", "三期", "40%", "50%", "尾款10%", "10%尾款"],
    2: ["12月31日", "2025-12-31", "逾期", "0.1%", "60日", "违约金"],
    3: ["归律所所有", "数据归属", "不得用于", "训练", "返还"],
    4: ["5年", "五年", "保密"],
    5: ["12%", "首年", "续费", "涨幅", "10%"],
    6: ["60日", "60天", "解约", "单方解除"],
    7: ["仲裁", "深圳"],
}


def verify_text_understand(path):
    out = {}
    for f in sorted(os.listdir(path)):
        if not f.endswith(".txt") or f.startswith("prompt"):
            continue
        model = f[:-4]
        text = open(os.path.join(path, f), encoding="utf-8").read()
        items = [l.strip() for l in text.splitlines() if l.strip()]
        items = [re.sub(r"^[\d一二三四五六七八九十]+[\.、)）]\s*|^[-*•]\s*", "", it) for it in items]
        hit = {}
        for it in items:
            for k, kws in TU_ITEMS.items():
                if hit.get(k):
                    continue
                if any(w in it for w in kws):
                    hit[k] = True
        n = sum(hit.values())
        over = [it for it in items if len(it) > 32]
        too_many = len(items) > 8 or len(items) < 3
        ok = n >= 5 and not over and not too_many
        detail = f"{n}/7 命中" + (f"；未覆盖: {[k for k in TU_ITEMS if k not in hit]}" if n < 7 else "")
        if over:
            detail += f"；超长条目 {len(over)} 条"
        if too_many:
            detail += f"；条数 {len(items)} 超限"
        out[model] = (ok, detail)
    return out, 1, 1


# ---------------- code_audit：5 植入缺陷，行号锚定 + 特征词，命中 ≥4 达标 ----------------
def _defect_anchors():
    prompt = open(os.path.join(OUT_ROOT, "code_audit", "prompt.txt"), encoding="utf-8").read()
    src = prompt.split("----")[1].strip()
    lines = src.splitlines()
    marks = {  # (标记行内容, 允许引用范围(缺陷所在函数体), 特征词)
        1: ("INSERT INTO fees", (3, 8), ["注入", "拼接", "sql", "SQL", "参数化"]),
        2: ("def approve_fee", (3, 17), ["越权", "权限", "校验", "鉴权", "授权", "owner", "任何人", "approve_fee", "归属", "审批", "操作人", "未使用"]),
        3: ("balance == 0.0", (19, 29), ["浮点", "精度", "round", "相等", "Decimal", "比较", "误差", "余额调整", "零值", "充值", "无需调整", "balance", "0时"]),
        4: ('open(out_path', (31, 38), ["句柄", "close", "with", "泄漏", "资源", "关闭", "释放"]),
        5: ("except Exception", (40, 48), ["异常", "except", "吞", "静默", "忽略", "跳过", "日志"]),
    }
    anchors = {}
    for i, (mark, span, kws) in marks.items():
        anchors[i] = (span, kws)
    return anchors


def verify_code_audit(path):
    anchors = _defect_anchors()
    out = {}
    for f in sorted(os.listdir(path)):
        if not f.endswith(".txt") or f.startswith("prompt"):
            continue
        model = f[:-4]
        text = open(os.path.join(path, f), encoding="utf-8").read()
        entries = []
        for ln in text.splitlines():
            m = re.match(r"^\s*(\d{1,3}(?:\s*[-~、,，]\s*\d{1,3})*)\s+", ln)
            if m:
                nums = [int(x) for x in re.findall(r"\d{1,3}", m.group(1))]
                entries.append((nums, ln))
        found = []
        for i, ((lo, hi), kws) in anchors.items():
            for nums, entry in entries:
                if any(lo - 1 <= n <= hi + 1 for n in nums) and any(k in entry for k in kws):
                    found.append(i)
                    break
        found = sorted(set(found))
        n = len(found)
        ok = n >= 4
        detail = f"{n}/5 检出" + (f"；未检出: {sorted(set(range(1,6))-set(found))}" if n < 5 else "")
        if not entries:
            detail = "无行号条目"
        out[model] = (ok, detail)
    return out, 1, 1


# ---------------- ui_design：结构断言（无外链/4 KPI/侧栏/趋势图/分布/明细表） ----------------
def verify_ui_design(path):
    out = {}
    for f in sorted(os.listdir(path)):
        if not f.endswith(".txt") or f.startswith("prompt"):
            continue
        model = f[:-4]
        html = strip_fences(open(os.path.join(path, f), encoding="utf-8").read())
        checks = {}
        checks["html完整title非空"] = ("<html" in html.lower() and "</html>" in html.lower()
                                        and bool(re.search(r"<title[^>]*>\s*\S", html, re.I)))
        kpi_words = sum(w in html for w in ["本季创收", "在办案件", "客户总数", "回款率"])
        kpi_cls = len(re.findall(r'class="[^"]*(?:kpi|stat|metric|indicator)[^"]*"', html, re.I))
        checks["KPI指标卡"] = kpi_words >= 3 and kpi_cls >= 3
        nav_words = sum(w in html for w in ["案件管理", "客户管理", "财务管理", "系统设置"])
        checks["深色侧栏导航"] = bool(re.search(r"<(nav|aside)", html, re.I)) and nav_words >= 3
        month_axis = sum(f"{i}月" in html for i in range(1, 13))
        has_chart = bool(re.search(r"<(svg|canvas)", html, re.I)) or len(re.findall(r"class=\"[^\"]*bar", html)) >= 6
        marks = len(re.findall(r"<(rect|circle|polyline|polygon)\b", html, re.I)) \
            + len(re.findall(r"class=\"[^\"]*(?:bar|point|col|mark)[^\"]*\"", html, re.I))
        checks["趋势图(容器+数据标记)"] = has_chart and (marks >= 6 or month_axis >= 6)
        dist_words = sum(w in html for w in ["进行中", "已归档", "待立案", "已结案"])
        checks["案件状态分布"] = dist_words >= 3
        trs = len(re.findall(r"<tr[ >]", html, re.I))
        head_words = sum(w in html for w in ["案号", "客户", "案件类型", "承办律师", "标的额", "状态"])
        checks["明细表(≥6行+表头)"] = ("<table" in html.lower()) and trs >= 6 and head_words >= 4
        leaks = re.findall(r'<script[^>]*\ssrc=|<link[^>]*\shref=|@import|url\(\s*["\']?http|<img[^>]*\ssrc=["\']http', html, re.I)
        checks["无外部资源链接"] = len(leaks) == 0
        fails = [k for k, v in checks.items() if not v]
        ok = not fails
        detail = "全结构 ✓" if ok else f"缺: {fails}"
        out[model] = (ok, detail)
    return out, 1, 1


VERIFIERS = {"code_gen_hard": verify_code_gen_hard, "data_analysis": verify_data_analysis,
             "text_understand": verify_text_understand, "code_audit": verify_code_audit,
             "ui_design": verify_ui_design}


def main():
    print(f"=== 自动验收 证据根: {OUT_ROOT} ===")
    summary = {}
    for task in TASKS:
        path = os.path.join(OUT_ROOT, task)
        if not os.path.isdir(path):
            print(f"[skip] {task} 无目录")
            continue
        vf = VERIFIERS[task]
        results, need, gate = vf(path)
        lines = [f"# {task} 测评结果（2026-09-04 第二批自动验收）", ""]
        table = []
        for model in sorted(results):
            if task == "code_gen_hard":
                got, detail = results[model]
                ok = got >= gate
            elif task == "data_analysis":
                got, detail = results[model]
                ok = got >= gate
            else:
                ok, detail = results[model]
            mark = "✓ 达标" if ok else "✗"
            table.append(f"| {MODEL_LABEL.get(model, model)} | {detail} | {mark} |")
            summary.setdefault(task, {})[model] = "达标" if ok else f"未达标({detail})"
        lines.append("| 模型 | 明细 | 判定 |")
        lines.append("|---|---|---|")
        lines += table
        lines += ["", f"> 达标线：自动验收（code_gen_hard 8/8 断言；data_analysis 5/5 黄金值 ±0.5%；其余结构/要点门限见明细）；双盲评分后置"]
        open(os.path.join(OUT_ROOT, f"{task}_结果.md"), "w", encoding="utf-8").write("\n".join(lines))
        npass = 0
        for v in results.values():
            if isinstance(v[0], bool):
                npass += int(v[0])
            else:
                npass += int(v[0] >= gate)
        print(f"[{task}] 达标 {npass}/{len(results)}")
    json.dump({t: {m: d for m, d in ms.items()} for t, ms in summary.items()},
              open(os.path.join(OUT_ROOT, "_verify2.json"), "w"), ensure_ascii=False, indent=1)
    print("完成 → evidence/<task>_结果.md + _verify2.json")


if __name__ == "__main__":
    main()
