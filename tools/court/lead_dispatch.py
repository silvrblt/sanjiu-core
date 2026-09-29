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
    "codex": {"role": "明确spec编码执行体", "mode": "codex", "note": "codex exec 无头执行（沙箱禁网）"},
}


def _read_settings():
    try:
        with open(SETTINGS, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return ""


def _write_settings(text):
    with open(SETTINGS, "w", encoding="utf-8") as f:
        f.write(text)


def _set_default(provider, model):
    """临时写 agent-default-model；返回还原函数。"""
    original = _read_settings()
    lines = [l for l in original.splitlines()
             if not l.strip().startswith(("agent-default-model:", "provider:", "model:"))]
    lines.append("agent-default-model:")
    lines.append(f"  provider: {provider}")
    lines.append(f"  model: {model}")
    _write_settings("\n".join(lines) + "\n")

    def restore():
        _write_settings(original)
    return restore


def dispatch(combo, card, prompt="", timeout=120):
    seat = SEAT_MAP[combo]
    task_text = " ".join(str(card.get(k) or "") for k in ("title", "description", "prompt"))
    full = f"{prompt}\n\n任务卡：{task_text}" if prompt else f"任务卡：{task_text}"
    if seat["mode"] == "session":
        return {"mode": "session", "role": seat["role"], "note": seat["note"],
                "instruction": full, "ok": True}
    restore = _set_default(seat["provider"], seat["model"])
    try:
        t0 = time.time()
        r = subprocess.run(["dsh", "--profile", "headless", full],
                           capture_output=True, text=True, timeout=timeout)
        cost_s = round(time.time() - t0, 1)
        ok = r.returncode == 0 and r.stdout.strip()
        return {"mode": "dsh", "provider": seat["provider"], "model": seat["model"],
                "role": seat["role"], "ok": ok, "exit": r.returncode, "cost_s": cost_s,
                "output": r.stdout.strip()[:500],
                "fallback": "窗口会话+人工" if not ok else None}
    except subprocess.TimeoutExpired:
        return {"mode": "dsh", "provider": seat["provider"], "model": seat["model"],
                "role": seat["role"], "ok": False, "cost_s": timeout,
                "output": "", "fallback": f"超时>{timeout}s 降级窗口会话+人工",
                "gate_record": "FLOW_ERR_MELTDOWN"}
    finally:
        restore()


def _selftest():
    fails = []
    def check(name, cond):
        print(("PASS " if cond else "FAIL ") + name)
        if not cond: fails.append(name)
    check("席位映射：A=session 一审承办", SEAT_MAP["A"]["mode"] == "session")
    check("席位映射：B=dsh 豆包", SEAT_MAP["B"] == {"role": "二审承办", "mode": "dsh",
          "provider": "ark", "model": "doubao-seed-2-1-turbo-260628"})
    check("席位映射：B_appeal=dsh GLM", SEAT_MAP["B_appeal"]["provider"] == "zhipu")
    # settings 写还（不真跑 dsh）
    restore = _set_default("ark", "doubao-seed-2-1-turbo-260628")
    after = _read_settings()
    check("settings 写入含 provider/model", "provider: ark" in after and "model: doubao-seed-2-1-turbo-260628" in after)
    restore()
    after2 = _read_settings()
    check("settings 还原", "provider: ark" not in after2.splitlines())
    # session 分发
    r = dispatch("A", {"title": "测试"}, "")
    check("A 分发为 session 模式", r["mode"] == "session" and r["ok"])
    print(f"\n共 5 项断言，失败 {len(fails)}")
    return 1 if fails else 0


def main(argv):
    if "--selftest" in argv:
        sys.exit(_selftest())
    if "--combo" not in argv:
        print(__doc__)
        return 0
    combo = argv[argv.index("--combo") + 1]
    card_path = argv[argv.index("--card") + 1]
    prompt = argv[argv.index("--prompt") + 1] if "--prompt" in argv else ""
    timeout = int(argv[argv.index("--timeout") + 1]) if "--timeout" in argv else 120
    card = json.load(open(card_path, encoding="utf-8"))
    print(json.dumps(dispatch(combo, card, prompt, timeout), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
