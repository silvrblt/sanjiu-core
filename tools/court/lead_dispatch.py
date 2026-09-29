#!/usr/bin/env python3
"""承办分发器 v0（2026-09-29，完整落地定稿 R02/P0-8 阶段3）

三选一判决后的承办执行分发：
  模式 A → 一审承办 = 当前会话（DeepSeek V4 Flash）→ 输出会话承办指引；
  模式 B → 二审承办 = 豆包（dsh pi-ai: ark/doubao-seed-2-1-turbo-260628）→ dsh headless 执行；
  上诉级三审承办 → GLM（zhipu/glm-5.3）→ dsh headless 执行。
分发协议：临时写 ~/.dsh/settings.yaml 的 agent-default-model → dsh --profile headless 执行 →
还原 settings；120s 硬超时降级回窗口会话并记闸门记录。

用法：
  python3 lead_dispatch.py --selftest
  python3 lead_dispatch.py --combo B --card <任务卡.json> [--prompt "承办指令"] [--timeout 120]
"""
import json
import os
import subprocess
import sys
import time

SETTINGS = os.path.expanduser("~/.dsh/settings.yaml")

SEAT_MAP = {
    "A": {"role": "一审承办", "mode": "session", "note": "DeepSeek V4 Flash（当前会话即承办）"},
    "B": {"role": "二审承办", "mode": "dsh", "provider": "ark",
          "model": "doubao-seed-2-1-turbo-260628"},
    "B_appeal": {"role": "三审承办（上诉级）", "mode": "dsh", "provider": "zhipu",
                 "model": "glm-5.3"},
}
EXECUTOR_MAP = {
    "codex": {"role": "明确spec编码执行体", "mode": "codex", "note": "codex exec 无头执行（沙箱禁网）"},
}


def _read_settings():
    try:
        with open(SETTINGS, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return None  # None = 文件不存在


def _settings_text(s):
    return s if s is not None else ""


def _write_settings(text):
    os.makedirs(os.path.dirname(SETTINGS), exist_ok=True)
    tmp = SETTINGS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, SETTINGS)  # 原子写


def _set_default(provider, model):
    """临时替换 agent-default-model 节（仅该节，行级精确）；返回还原函数。"""
    original = _read_settings()
    lines = (original or "").splitlines()
    out, i = [], 0
    while i < len(lines):
        line = lines[i]
        if line.strip() == "agent-default-model:":
            i += 1
            while i < len(lines) and (lines[i].startswith(("  ", "\t"))
                                       and lines[i].strip().split(":", 1)[0] in ("provider", "model")):
                i += 1
            continue
        out.append(line)
        i += 1
    out.append("agent-default-model:")
    out.append(f"  provider: {provider}")
    out.append(f"  model: {model}")
    _write_settings("\n".join(out) + "\n")

    def restore():
        if original is None:
            try:
                os.remove(SETTINGS)
            except FileNotFoundError:
                pass
        else:
            _write_settings(original)
    return restore


def dispatch(combo, card, prompt="", timeout=120, receipt_id=None, seat_override=None):
    seat = dict(EXECUTOR_MAP[seat_override] if seat_override else SEAT_MAP[combo])
    task_text = " ".join(str(card.get(k) or "") for k in ("title", "description", "prompt"))
    full = f"{prompt}\n\n任务卡：{task_text}" if prompt else f"任务卡：{task_text}"
    if seat["mode"] == "session":
        return {"mode": "session", "role": seat["role"], "note": seat["note"],
                "instruction": full, "ok": True, "receipt_id": receipt_id}
    if seat["mode"] == "codex":
        t0 = time.time()
        try:
            try:
                r = subprocess.run(["codex", "exec", "--skip-git-repo-check", full],
                                   capture_output=True, text=True, timeout=timeout)
            except FileNotFoundError:
                return {"mode": "codex", "role": seat["role"], "ok": False,
                        "exit": "MISSING_BINARY", "cost_s": 0.0, "output": "",
                        "fallback": "codex 二进制缺失：降级窗口会话+人工",
                        "receipt_id": receipt_id}
            except PermissionError:
                return {"mode": "codex", "role": seat["role"], "ok": False,
                        "exit": "PERMISSION_DENIED", "cost_s": 0.0, "output": "",
                        "fallback": "codex 无执行权限：降级窗口会话+人工",
                        "receipt_id": receipt_id}
            except OSError:
                return {"mode": "codex", "role": seat["role"], "ok": False,
                        "exit": "OSERROR", "cost_s": 0.0, "output": "",
                        "fallback": "codex 启动失败：降级窗口会话+人工",
                        "receipt_id": receipt_id}
            cost_s = round(time.time() - t0, 1)
            ok = r.returncode == 0 and bool(r.stdout.strip())
            return {"mode": "codex", "role": seat["role"], "ok": ok, "exit": r.returncode,
                    "cost_s": cost_s, "output": r.stdout.strip()[:500],
                    "fallback": "窗口会话+人工" if not ok else None,
                    "receipt_id": receipt_id}
        except subprocess.TimeoutExpired:
            return {"mode": "codex", "role": seat["role"], "ok": False, "cost_s": timeout,
                    "output": "", "fallback": f"超时>{timeout}s 降级窗口会话+人工",
                    "gate_record": "timeout_fallback",
                    "receipt_id": receipt_id}
    restore = _set_default(seat["provider"], seat["model"])
    try:
        t0 = time.time()
        try:
            r = subprocess.run(["dsh", "--profile", "headless", full],
                               capture_output=True, text=True, timeout=timeout)
        except FileNotFoundError:
            return {"mode": "dsh", "provider": seat["provider"], "model": seat["model"],
                    "role": seat["role"], "ok": False, "exit": "MISSING_BINARY",
                    "cost_s": 0.0, "output": "",
                    "fallback": "dsh 二进制缺失：降级窗口会话+人工",
                    "receipt_id": receipt_id}
        except PermissionError:
            return {"mode": "dsh", "provider": seat["provider"], "model": seat["model"],
                    "role": seat["role"], "ok": False, "exit": "PERMISSION_DENIED",
                    "cost_s": 0.0, "output": "",
                    "fallback": "dsh 无执行权限：降级窗口会话+人工",
                    "receipt_id": receipt_id}
        except OSError:
            return {"mode": "dsh", "provider": seat["provider"], "model": seat["model"],
                    "role": seat["role"], "ok": False, "exit": "OSERROR",
                    "cost_s": 0.0, "output": "",
                    "fallback": "dsh 启动失败：降级窗口会话+人工",
                    "receipt_id": receipt_id}
        cost_s = round(time.time() - t0, 1)
        ok = r.returncode == 0 and bool(r.stdout.strip())
        return {"mode": "dsh", "provider": seat["provider"], "model": seat["model"],
                "role": seat["role"], "ok": ok, "exit": r.returncode, "cost_s": cost_s,
                "output": r.stdout.strip()[:500],
                "fallback": "窗口会话+人工" if not ok else None,
                "receipt_id": receipt_id}
    except subprocess.TimeoutExpired:
        return {"mode": "dsh", "provider": seat["provider"], "model": seat["model"],
                "role": seat["role"], "ok": False, "cost_s": timeout,
                "output": "", "fallback": f"超时>{timeout}s 降级窗口会话+人工",
                "gate_record": "timeout_fallback",
                "receipt_id": receipt_id}
    finally:
        restore()


def _selftest():
    fails = []
    total = [0]
    def check(name, cond):
        total[0] += 1
        print(("PASS " if cond else "FAIL ") + name)
        if not cond: fails.append(name)
    check("席位映射：A=session 一审承办", SEAT_MAP["A"]["mode"] == "session")
    check("席位映射：B=dsh 豆包", SEAT_MAP["B"] == {"role": "二审承办", "mode": "dsh",
          "provider": "ark", "model": "doubao-seed-2-1-turbo-260628"})
    check("席位映射：B_appeal=dsh GLM", SEAT_MAP["B_appeal"]["provider"] == "zhipu")
    # settings 写还（不真跑 dsh）
    original_before = _read_settings()
    restore = _set_default("ark", "doubao-seed-2-1-turbo-260628")
    after = _read_settings()
    check("settings 写入含 provider/model", "provider: ark" in after and "model: doubao-seed-2-1-turbo-260628" in after)
    restore()
    check("settings 还原为原始内容全等", _read_settings() == original_before)
    # session 分发
    r = dispatch("A", {"title": "测试"}, "")
    check("A 分发为 session 模式", r["mode"] == "session" and r["ok"])
    print(f"\n共 {total[0]} 项断言，失败 {len(fails)}")
    return 1 if fails else 0


def main(argv):
    if "--selftest" in argv:
        sys.exit(_selftest())
    import argparse
    ap = argparse.ArgumentParser(prog="lead_dispatch", description="三审九方承办分发器")
    ap.add_argument("--combo", choices=sorted(SEAT_MAP.keys()))
    ap.add_argument("--seat", default=None, choices=sorted(EXECUTOR_MAP.keys()),
                    help="执行体覆盖（codex=明确spec编码；缺省按 combo 席位）")
    ap.add_argument("--receipt", default=None, help="立案庭回执 JSON（可选，透传+校验）")
    ap.add_argument("--card", default=None)
    ap.add_argument("--prompt", default="")
    ap.add_argument("--timeout", type=int, default=120)
    try:
        args = ap.parse_args(argv)
    except SystemExit:
        print(json.dumps({"ok": False, "error": "argparse_error"}, ensure_ascii=False))
        return 2
    if not args.combo or not args.card:
        print(json.dumps({"ok": False, "error": "combo_and_card_required"}, ensure_ascii=False))
        return 2
    combo, card_path, prompt, timeout = args.combo, args.card, args.prompt, args.timeout
    receipt_id = None
    if args.receipt:
        with open(args.receipt, encoding="utf-8") as f:
            receipt_id = json.load(f).get("receipt_id")
    try:
        with open(card_path, encoding="utf-8") as f:
            card = json.load(f)
    except (OSError, ValueError) as e:
        print(f"lead_dispatch: 任务卡读取失败（{e}）", file=sys.stderr)
        return 2
    if not isinstance(card, dict):
        print("lead_dispatch: 任务卡必须为 JSON 对象", file=sys.stderr)
        return 2
    print(json.dumps(dispatch(combo, card, prompt, timeout, receipt_id, args.seat), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
