#!/usr/bin/env python3
"""三审九方 · 命令行启动页（onboard.py）

面向新接入用户的交互式入口：项目介绍 / 优势与劣势 / 两种模式 / 九席矩阵 /
席位模型选择 / API 密钥配置 / 环境自检。配置目录 ~/.sanjiu/ 为 700、文件为 600 权限，
不入库、不上传。

用法：
  python3 tools/onboard.py            # 交互式启动页
  python3 tools/onboard.py --selftest # 自测（非交互）
  python3 tools/onboard.py --status   # 只看环境自检
"""
import getpass
import json
import os
import shlex
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
CONFIG_DIR = os.path.expanduser("~/.sanjiu")
SEATS_OVERRIDE = os.path.join(CONFIG_DIR, "seats-override.yaml")
API_KEYS_FILE = os.path.join(CONFIG_DIR, "api-keys.env")

try:
    import yaml
except ImportError:
    yaml = None

SEATS = {
    "l1_lead":       {"role": "一审·承办",    "default_model": "deepseek-v4-flash",         "key": "DEEPSEEK_API_KEY",
                      "candidates": ["deepseek-v4-flash", "glm-5.3-flash"]},
    "l1_antagonist": {"role": "一审·对抗审计", "default_model": "hunyuan-hy3",             "key": "HUNYUAN_API_KEY",
                      "candidates": ["hunyuan-hy3", "qwen3.8-max"]},
    "l1_judge":      {"role": "一审·裁决",    "default_model": "minimax-m3",               "key": "MINIMAX_API_KEY",
                      "candidates": ["MiniMax-M3", "kimi-k2.7-code"]},
    "l2_lead":       {"role": "二审·承办",    "default_model": "doubao-2.1-turbo",         "key": "ARK_API_KEY",
                      "candidates": ["doubao-2.1-turbo", "deepseek-v4-pro"]},
    "l2_antagonist": {"role": "二审·对抗审计", "default_model": "deepseek-v4-pro",          "key": "DEEPSEEK_API_KEY",
                      "candidates": ["deepseek-v4-pro", "doubao-2.1-turbo"]},
    "l2_judge":      {"role": "二审·裁决",    "default_model": "kimi-k2.7-code",           "key": "MOONSHOT_API_KEY",
                      "candidates": ["kimi-k2.7-code", "MiniMax-M3"]},
    "l3_lead":       {"role": "三审·承办",    "default_model": "glm-5.3",                  "key": "GLM_API_KEY",
                      "candidates": ["glm-5.3", "deepseek-v4-pro"]},
    "l3_antagonist": {"role": "三审·对抗审计", "default_model": "qwen3.8-max",              "key": "QWEN_API_KEY",
                      "candidates": ["qwen3.8-max", "glm-5.3"]},
    "l3_judge":      {"role": "三审·裁决",    "default_model": "kimi-k3",                  "key": "MOONSHOT_API_KEY",
                      "candidates": ["kimi-k3", "MiniMax-M3"]},
}

INTRO = r"""
╔══════════════════════════════════════════════════════════════╗
║              Sanjiu Core · 三审九方                           ║
║         多智能体对抗式审计与治理结构                             ║
╚══════════════════════════════════════════════════════════════╝
用 9 个异构模型席位组成三级交叉审查流水线：
承办产出 → 对抗审计（直接给出修改版方案）→ 裁决一次敲定。
消灭单一模型直接产出带来的幻觉、自证与平庸共识。

缘起：借鉴人类司法程序（起诉/辩护/审判）"以对抗与裁决约束偏见、平衡效率与真相"的理念
（非逐角色模仿），我们提出「三审九方」多智能体治理架构——它是多智能体辩论、反思-修正
等当前热议协同思路的一种工程化实践。
执行体可选：dsh（换模型承办）、codex（沙箱编码）为增强项，缺失或故障时自动降级为当前会话+人工；
核心机制为纯 Python 脚本（Python 3.9+，依赖 jsonschema 与 PyYAML），无需安装任何 harness。
"""

ADVANTAGES = """
┌─ 优势 ─────────────────────────────────────────────┐
│ 1. 相同质量输出下降低成本                            │
│    · 分级路由：简单问答不调用审计链（0 额外成本）      │
│    · 价格序排席：贵模型只放在低频审级                 │
│    · 前缀缓存：同材料多轮审计命中厂商缓存              │
│ 2. 质量保障：承办与对抗必须异模型，杜绝自审自纠        │
│ 3. 全程可追溯：材料包 schema + 路由回执 + 决策台账    │
└────────────────────────────────────────────────────┘
"""

DISADVANTAGES = """
┌─ 劣势（如实告知）───────────────────────────────────┐
│ 1. 时间拉长：多模型串联轮次，最短 2 轮、含上诉最长 6 轮 │
│    ——不适合超低延迟场景，适合质量优先任务              │
│ 2. 需要配置多厂商 API Key（本页提供配置向导）          │
│ 3. 这是流程与工具层：不训练模型、不做评测榜单          │
└────────────────────────────────────────────────────┘
"""

MODES = """
┌─ 两种审查模式 + 直答旁路（立案庭三选一）──────────────┐
│ 直答旁路   普通问答 → 当前模型直接回答，不调用审计链    │
│ 模式 A    常规任务 → 一审+二审（两级异模型审查）        │
│ 模式 B    对外交付/资金/法律/安全等 → 二审+三审（终局） │
│ （两种模式 = 模式 A / 模式 B；直答为成本旁路）          │
└────────────────────────────────────────────────────┘
"""


def _format_key_line(env, value):
    """API key 行格式化：shlex.quote 转义，拒绝换行。返回 (行, None) 或 (None, 原因)。"""
    if "\n" in value or "\r" in value:
        return None, "换行符非法"
    return f"{env}={shlex.quote(value)}", None


def _load_overrides():
    if not (yaml and os.path.exists(SEATS_OVERRIDE)):
        return {}
    try:
        with open(SEATS_OVERRIDE, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def _seat_model(seat_id):
    ov = _load_overrides()
    if seat_id in ov and ov[seat_id]:
        return ov[seat_id]
    return SEATS[seat_id]["default_model"]


def _show_matrix():
    print("\n九席矩阵（当前生效模型）：\n")
    print("  席位            | 角色       | 模型")
    print("  " + "-" * 56)
    for sid, s in SEATS.items():
        mark = "*" if sid in _load_overrides() else " "
        print(f"  {sid:14s} | {s['role']:10s} | {_seat_model(sid)} {mark}")
    print("  （* = 用户自定义）")
    print("\n约束：承办与对抗必须异模型；同审级同厂互斥。")


def _pick_seat():
    ids = list(SEATS.keys())
    print("\n选择要配置的席位：")
    for i, sid in enumerate(ids, 1):
        print(f"  {i}) {sid:14s} {SEATS[sid]['role']}  当前={_seat_model(sid)}")
    try:
        idx = int(input("输入编号（0 返回）：").strip())
    except ValueError:
        return
    if not 1 <= idx <= len(ids):
        return
    sid = ids[idx - 1]
    print(f"\n{sid}（{SEATS[sid]['role']}）候选模型：")
    for j, m in enumerate(SEATS[sid]["candidates"], 1):
        print(f"  {j}) {m}" + ("  ← 默认" if m == SEATS[sid]["default_model"] else ""))
    try:
        j = int(input("选择（0 返回）：").strip())
    except ValueError:
        return
    if not 1 <= j <= len(SEATS[sid]["candidates"]):
        return
    chosen = SEATS[sid]["candidates"][j - 1]
    if _save_override(sid, chosen):
        print(f"✓ {sid} → {chosen}（写入 ~/.sanjiu/seats-override.yaml）")
    else:
        print("✗ 配置未保存（依赖缺失）")


def _vendor_of(model):
    if model.startswith(("deepseek", "ds-")): return "deepseek"
    if model.startswith(("glm",)): return "zhipu"
    if model.startswith(("kimi", "moonshot")): return "moonshot"
    if model.startswith(("MiniMax", "minimax")): return "minimax"
    if model.startswith(("doubao",)): return "bytedance"
    if model.startswith(("qwen",)): return "alibaba"
    if model.startswith(("hunyuan", "hy3")): return "tencent"
    return model.lower()


def _constraint_violation(sid, model):
    """同审级同厂互斥 + 承办与对抗必须异模型；违例返回原因字符串，合规返回 None。"""
    stage = sid.split("_")[0]          # l1/l2/l3
    role = sid.split("_")[1]           # lead/antagonist/judge
    ov = _load_overrides()
    # 生效模型 = override 优先，否则默认值（约束对默认配置同样成立）
    other = {}
    for oid, oseat in SEATS.items():
        if oid == sid or oid.split("_")[0] != stage:
            continue
        other[oid] = ov.get(oid) or oseat["default_model"]
    # 同审级同厂互斥
    for oid, omodel in other.items():
        if omodel and _vendor_of(omodel) == _vendor_of(model):
            return f"同审级同厂互斥：{oid} 已用 {omodel}（{_vendor_of(model)}）"
    # 承办与对抗必须异模型
    if role in ("lead", "antagonist"):
        peer_role = "antagonist" if role == "lead" else "lead"
        peer_id = f"{stage}_{peer_role}"
        peer_model = other.get(peer_id)
        if peer_model and peer_model == model:
            return f"承办与对抗必须异模型：{peer_id} 已用同款 {model}"
    return None


def _save_override(sid, model):
    os.makedirs(CONFIG_DIR, mode=0o700, exist_ok=True)
    if yaml is None:
        print("⚠ 需要 PyYAML（pip install pyyaml）")
        return False
    err = _constraint_violation(sid, model)
    if err:
        print(f"✗ 拒绝写入：{err}")
        return False
    ov = _load_overrides()
    ov[sid] = model
    tmp = SEATS_OVERRIDE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        yaml.safe_dump(ov, f, allow_unicode=True)
    os.chmod(tmp, 0o600)
    os.replace(tmp, SEATS_OVERRIDE)  # 原子替换，防并发覆盖丢失
    return True


def _configure_keys():
    print("\nAPI Key 配置（写入 ~/.sanjiu/api-keys.env，600 权限，不入库）：")
    print("回车跳过 = 保持现状。")
    key_by_env = {}
    for s in SEATS.values():
        key_by_env.setdefault(s["key"], s["role"])
    envs = list(key_by_env.keys())
    values = {}
    try:
        for env in envs:
            cur = os.environ.get(env, "")
            hint = f"（已配置，回车保留）" if cur else "（未配置）"
            v = getpass.getpass(f"  {env} {hint}: ").strip()
            if v:
                line, err = _format_key_line(env, v)
                if err:
                    print(f"  ✗ {env} {err}，已跳过")
                    continue
                values[env] = line
    except (EOFError, KeyboardInterrupt):
        print("\n已取消，返回菜单。")
        return
    if values:
        os.makedirs(CONFIG_DIR, mode=0o700, exist_ok=True)
        with open(API_KEYS_FILE, "w", encoding="utf-8") as f:
            for line in values.values():
                f.write(line + "\n")
        os.chmod(API_KEYS_FILE, 0o600)
        print(f"✓ 已写入 {API_KEYS_FILE}")
        print(f"  生效方式：source {API_KEYS_FILE}（或加入 shell 配置）")
    else:
        print("未变更。")


def status():
    lines = ["环境自检（范围：配置完整性与工具可用性；不验证质量能力）："]
    ok_keys = 0
    for sid, s in SEATS.items():
        env = s["key"]
        has = bool(os.environ.get(env, ""))
        if has:
            ok_keys += 1
        lines.append(f"  [{'✓' if has else '·'}] {sid:14s} {s['role']:10s} 模型={_seat_model(sid):22s} {env}")
    unique_envs = len({s["key"] for s in SEATS.values()})
    lines.append(f"  API Key 已配置：{ok_keys}/{unique_envs} 个环境变量（席位间共用同名变量）")
    lines.append("  说明：上述为配置自检；质量与成本能力见 README「质量与成本」节（设计目标与实测口径）")
    return "\n".join(lines)


def _selftest():
    fails = 0
    def chk(name, cond):
        nonlocal fails
        print(("PASS " if cond else "FAIL ") + name)
        if not cond:
            fails += 1
    chk("九席定义完整", len(SEATS) == 9)
    chk("每席含 key/candidates", all(s.get("key") and s.get("candidates") for s in SEATS.values()))
    chk("默认席位矩阵可渲染", _seat_model("l1_lead") == "deepseek-v4-flash")
    chk("override 持久化往返", _override_roundtrip())
    line, err = _format_key_line("TEST_API_KEY", 'sk-abc"def$x y')
    chk("key 格式化转义", line == "TEST_API_KEY=" + shlex.quote('sk-abc"def$x y') and err is None)
    _, err2 = _format_key_line("TEST_API_KEY", "bad\nkey")
    chk("key 换行拒绝", err2 is not None)
    chk("status 输出非空", bool(status().strip()))
    print(f"\n共 7 项断言，失败 {fails}")
    return 1 if fails else 0


def _override_roundtrip():
    if yaml is None:
        print("  （PyYAML 缺失，跳过 override 往返）")
        return True
    import tempfile
    global SEATS_OVERRIDE
    real_path = SEATS_OVERRIDE
    with tempfile.TemporaryDirectory() as tmp:
        SEATS_OVERRIDE = os.path.join(tmp, "seats-override.yaml")
        _save_override("l3_judge", "MiniMax-M3")
        ok = _seat_model("l3_judge") == "MiniMax-M3"
        # 约束校验在隔离 override 下测试（依赖默认席位，与用户真实配置无关）
        ok = ok and _constraint_violation("l1_lead", "hunyuan-hy3") is not None
        ok = ok and _constraint_violation("l3_lead", "qwen3.8-max") is not None
        ok = ok and _constraint_violation("l2_lead", "glm-5.3-flash") is None
        SEATS_OVERRIDE = real_path
        return ok


def main(argv):
    if "--selftest" in argv:
        sys.exit(_selftest())
    if "--status" in argv:
        print(status())
        return 0
    print(INTRO)
    print(status())
    while True:
        print("""
  1) 项目介绍与优势劣势    2) 两种模式说明
  3) 九席矩阵（当前配置）  4) 席位模型选择
  5) API Key 配置         6) 环境自检
  0) 退出
""")
        try:
            c = input("选择：").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if c == "1":
            print(ADVANTAGES)
            print(DISADVANTAGES)
        elif c == "2":
            print(MODES)
        elif c == "3":
            _show_matrix()
        elif c == "4":
            _pick_seat()
        elif c == "5":
            _configure_keys()
        elif c == "6":
            print(status())
        elif c == "0":
            print("再见。完整文档见 README.md")
            return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
