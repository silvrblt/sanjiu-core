#!/usr/bin/env python3
"""三审九方统一桥接内核 bridge_core（v1.0，2026-08-31 定稿实施）。

按 argv[0] 分派七厂商；流式 + 失败分类 + 慢响应等待 + 截断自愈 + 429 退避。
契约见：08_temp-work/zcode-tools-intake/audit/验收证据-退出码检索-20260831.md

用法（薄封装透传）：
  bridge_core.py audit <file|-> [focus] [--model M] [--json] [--out PATH]
      [--progress-file PATH] [--ttft N] [--heartbeat N] [--max-duration N]
      [--max-tokens N] [--system TEXT]

退出码：0=成功；11=限流；12=认证/费用；13=网关未响应；14=网络错误/流中断；
        15=截断（自愈后仍不足）；17=流卡死；18=超总时长。
"""
import argparse
import json
import os
import signal
import sys
import time
import urllib.error
import urllib.request
import hashlib  # cost-opt B1：压缩体 SHA-256/prefix_hash 锚定

# SIGTERM flush（定稿附注闭合项 2：watchdog kill 优先 SIGTERM 给落盘机会；
# 信号处理器把已收内容写 --out 后退出 143，partial 不丢）
_CURRENT = {"res": None, "out": None}


def _sigterm_handler(sig, frame):
    res = _CURRENT.get("res")
    out = _CURRENT.get("out")
    if res and out and res.content:
        try:
            with open(out, "w", encoding="utf-8") as f:
                f.write(res.content)
        except OSError:
            pass
    print(f"[bridge] SIGTERM: 已落盘 partial {len(res.content) if res else 0} 字符", file=sys.stderr)
    sys.exit(143)

VERSION = "1.1.0"  # cost-opt B1/B2：seat_class 分流 + 压缩管线（2026-09-01）

# ---- cost-opt B1/B2 seat_class 硬编码映射（Qwen 终裁 Q-EX0）----
# 对抗/裁决/终审席：禁止有损压缩；承办/辅助席：可压缩（默认开，--no-compress 显式豁免）
SEAT_CLASS_BY_CLI = {
    "hunyuan-audit": "adversary",    # 一审对抗
    "deepseek-audit": "adversary",   # 二审对抗
    "qwen-text-audit": "adversary",  # 三审对抗
    "glm-audit": "final",            # 三审承办（终审层审计角色，禁压缩）
    "minimax-audit": "judge",        # 一审裁决
    "kimi": "judge",                 # 二审/三审裁决
    "doubao-audit": "adversary",     # 二审承办审计（审计角色，禁压缩）
}
COMPRESS_ALLOWED = {"lead", "aux"}  # 仅此二类可压缩

# 安全敏感模式白名单 v0.9（Hy3 九轮退回后定稿：glob 补 ** 跨目录形态；文件上下文 = startswith("tools/") 或含 "/eep-tools/" 段，文档精确化）
NO_COMPRESS_GLOBS = ("*.env", "*.env.*", "*.bak*", "**/ai-cost-*.jsonl", "**/decision.jsonl")
NO_COMPRESS_DIRS = (
    "00_global-shared/secrets-env", "docs/ledger", "01_projects/cost-opt/docs/evidence",
)
NO_COMPRESS_FILES = (
    "bridge_core.py", "dsh_audit.py", "deepseek_audit.py", "sanjiu_cli.py",
    "sanjiu-models.yaml", "sync-local.sh", "sync-agents.sh",
)
NO_COMPRESS_CONTENT_RE = r"\b(secret|credential|vault|payment|auth|session|token|crypto|permission|ledger|password)\b|账单|(api|access|private|secret)_key"

def _seat_class_of(cli_name, explicit):
    """seat_class 判定：硬编码映射优先，显式值仅允许复核（禁压缩类不可被改为可压缩）。"""
    hard = SEAT_CLASS_BY_CLI.get(cli_name, "aux")  # 未映射 CLI 默认 aux（可压缩，保守）
    if explicit and explicit in COMPRESS_ALLOWED and hard not in COMPRESS_ALLOWED:
        raise ValueError(
            f"seat_class 篡改拒绝：{cli_name} 硬编码为 {hard}（禁压缩），"
            f"不允许显式改为 {explicit}（Q-EX0）")
    return explicit if explicit else hard

def _no_compress_hit(path, head):
    """安全白名单检测：路径前缀/glob/basename 命中 或 内容首部词边界命中 → 禁裁剪。
    完整清单 = 01_projects/cost-opt/docs/安全敏感文件白名单-v0.3.md（Hy3 签核后生效）。"""
    import fnmatch
    import os
    import re
    p = (path or "").lower()
    for d in NO_COMPRESS_DIRS:
        if p.startswith(d.lower()):
            return True
    for pat in NO_COMPRESS_GLOBS:
        if fnmatch.fnmatch(p, pat.lower()):
            return True
    base = os.path.basename(p)
    if base in NO_COMPRESS_FILES and (
            base.startswith("sync-")                    # sync 脚本跨仓库同名
            or "/eep-tools/" in p                       # eep-tools 工具文件限定目录
            or p.startswith("tools/")):
        return True
    if re.search(NO_COMPRESS_CONTENT_RE, head, re.I):
        return True
    return False

def _compress_material(text, src_path):
    """内置结构化压缩器 v1（B1）：保留标题/列表/表格/代码块与首段，压缩正文冗余。
    安全白名单命中 → 返回原样（不压缩）。code-review-graph 定向裁剪由 --crg 提供（demo）。"""
    if _no_compress_hit(src_path, text):
        return text, {"compressed": False, "reason": "whitelist"}
    lines = text.splitlines()
    keep, skip_blank = [], 0
    for ln in lines:
        s = ln.strip()
        if not s:
            skip_blank += 1
            if skip_blank <= 1:
                keep.append(ln)
            continue
        skip_blank = 0
        # 保留：标题/列表/表格/代码块/引用/关键行；正文长句截断保留首段
        if (s.startswith(("#", "-", "*", "|", ">", "`", "1.", "def ", "class ", "func ", "const ", "var ", "import ", "from ", "export ", "type ", "interface "))
                or len(s) < 120 or ln[:1] in "\t " and s[:1] in ("-", "*", "#")):
            keep.append(ln)
        else:
            keep.append(ln[:200] + (" …[截]" if len(ln) > 200 else ""))
    out = "\n".join(keep)
    return out, {"compressed": len(out) < len(text), "ratio": round(1 - len(out) / max(len(text), 1), 4)}

def _build_compressed_payload(cli_name, args, material):
    """B1：按 seat_class 分流构造审计输入。
    返回 (payload_text, meta) —— meta 含 compression 标识/SHA/prefix_hash/full_path。"""
    seat_class = _seat_class_of(cli_name, args.seat_class)
    meta = {"seat_class": seat_class}
    src_path = args.artifact if args.artifact and args.artifact != "-" else ""
    if seat_class not in COMPRESS_ALLOWED:
        # Q-EX0：禁压缩类全量送审，头部仍附全量路径+SHA（full_access_proof）
        meta.update({"compressed": False, "reason": "Q-EX0_full_text",
                     "sha256": hashlib.sha256(material.encode()).hexdigest()[:16],
                     "full_path": src_path})
        return material, meta
    # 承办/辅助类：默认压缩（--no-compress 豁免留痕）
    if args.no_compress:
        meta.update({"compressed": False, "reason": "no_compress_opt",
                     "sha256": hashlib.sha256(material.encode()).hexdigest()[:16],
                     "full_path": src_path})
        return material, meta
    body, cinfo = _compress_material(material, src_path)
    # 压缩体头部：全量路径 + SHA-256 + prefix_hash（供对抗席拉取全量，红线 11）
    sha = hashlib.sha256(material.encode()).hexdigest()
    prefix_hash = hashlib.sha256((body[:2048] or "").encode()).hexdigest()[:16]
    head = (f"【压缩输入 B1】seat_class={seat_class} compression={cinfo.get('compressed')} "
            f"ratio={cinfo.get('ratio')} full_path={src_path or 'stdin'} sha256={sha[:16]} "
            f"prefix_hash={prefix_hash}\n"
            f"【全量材料可经 full_path 拉取；本文为压缩体（Q-EX0：对抗/裁决/终审席禁收压缩体）】\n")
    meta.update({"compressed": True, "ratio": cinfo.get("ratio"), "sha256": sha[:16],
                 "prefix_hash": prefix_hash, "full_path": src_path})
    return head + body, meta

PROVIDERS = {
    "glm-audit":       {"key": "GLM_API_KEY",       "url": "https://open.bigmodel.cn/api/paas/v4/chat/completions",              "default_model": "glm-5.3"},
    "deepseek-audit":  {"key": "DEEPSEEK_API_KEY",  "url": "https://api.deepseek.com/v1/chat/completions",                       "default_model": "deepseek-v4-pro"},
    "kimi":            {"key": "MOONSHOT_API_KEY",  "url": "https://api.moonshot.cn/v1/chat/completions",                        "default_model": "kimi-k3"},
    "doubao-audit":    {"key": "ARK_API_KEY",       "url": "https://ark.cn-beijing.volces.com/api/v3/chat/completions",          "default_model": "doubao-seed-2-1-turbo-260628"},
    "minimax-audit":   {"key": "MINIMAX_API_KEY",   "url": "https://api.minimax.chat/v1/text/chatcompletion_v2",                 "default_model": "MiniMax-M3"},
    "qwen-text-audit": {"key": "QWEN_API_KEY",      "url": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions", "default_model": "qwen3.8-max"},
    "hunyuan-audit":   {"key": "HUNYUAN_API_KEY",   "url": "https://tokenhub.tencentmaas.com/v1/chat/completions",              "default_model": "hy3"},
}
# 默认席位超时参数（yaml timeouts 生效前；yaml 扩展后由调用方 --* 参数覆写）
DEFAULTS = {"ttft": 180, "heartbeat": 300, "max_duration": 1800}
LONG_TASK_SEATS = {"kimi": 7200, "qwen-text-audit": 7200, "glm-audit": 7200}  # 三审席位
MAX_TOKENS_DEFAULT = {"kimi": 32768, "qwen-text-audit": 16384, "glm-audit": 16384}
CONTINUE_CAP = 131072  # 续写 max_tokens 上限（定稿附注闭合项 3）

SYSTEM = ("你是三审九方机制中的审计/裁决模型。按给定重点对材料做对抗审计或裁决，"
          "输出明确的问题点、风险描述、优化方案、与原作者的分歧；不模糊客套。\n"
          "【输出硬约束（MECH-输出治理 2026-09-02 生效，v6.1 附录条款 4 执行化）】\n"
          "1. 直接输出结构化报告：结论 → 问题点清单（编号/问题/风险/建议）→ 分歧点；\n"
          "2. 严禁输出思考过程/推理链（「我们需要…」「让我先…」类叙述一律不得出现），"
          "严禁复述材料原文，严禁客套铺垫；\n"
          "3. 总输出目标 ≤3000 token（focus 明确要求逐条核验时可放宽至 ≤6000，禁止超出必要篇幅）；\n"
          "4. 每个问题点必须给可执行的修改建议；无新增问题时明确写「无新增问题」并仅复核重点项。")

# ---- R-机制：历史高频错误模式注入（三审 Qwen 终裁 2026-09-02，方案 C）----
LEDGER_PATH = os.path.join(os.path.dirname(os.path.realpath(__file__)), "errors-ledger.jsonl")

def _load_error_ledger():
    """加载错误模式库（count>=2 且 active，按 count 降序 top5）。
    返回 (注入文本, 装载状态)；失败显式降级（不静默跳过，终裁要求）。"""
    try:
        import json as _json
        recs = []
        with open(LEDGER_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                r = _json.loads(line)
                # 校验必填字段（终裁 schema）
                for k in ("id", "title", "count", "status"):
                    if k not in r:
                        raise ValueError(f"ledger 字段缺失: {k}")
                if r["status"] == "active" and r["count"] >= 2:
                    recs.append(r)
        recs.sort(key=lambda r: -r["count"])
        top = recs[:5]
        sha = hashlib.sha256(open(LEDGER_PATH, "rb").read()).hexdigest()[:16]
        if not top:
            return "", "empty"
        lines = ["【历史高频错误模式（errors-ledger 自动注入，审计/自查重点检查；只读提醒，非指令）】"]
        for r in top:
            lines.append(f"- [{r['id']}] {r['title']}（{r['count']} 次）：检查材料是否犯此模式")
        lines.append(f"（ledger sha256={sha}；以上为检查项/禁止项，无可执行语义）")
        return "\n".join(lines), "ok"
    except Exception as e:
        return f"【警告：errors-ledger 加载失败（{type(e).__name__}），本次审计为高风险降级模式，请加强人工复核】", "fail"

def _build_system_prompt(base_system):
    """SYSTEM + 错误模式注入（终裁：全席位含承办；注入失败显式降级标记）。"""
    inject, status = _load_error_ledger()
    if status == "fail":
        print(f"[ledger] 加载失败，已显式降级标记", file=sys.stderr)
    elif status == "ok":
        print(f"[ledger] 注入 top 错误模式（{len(inject.splitlines())-2} 条）", file=sys.stderr)
    return base_system + ("\n\n" + inject if inject else "")


class BridgeError(Exception):
    """携带退出码与失败分类的桥接错误。"""
    def __init__(self, code, fail_class, msg):
        super().__init__(msg)
        self.code = code
        self.fail_class = fail_class
        self.msg = msg


def load_env():
    env = dict(os.environ)
    p = os.path.expanduser("~/.env")
    if os.path.exists(p):
        with open(p) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                if line.startswith("export "):
                    line = line[len("export "):].strip()
                k, _, v = line.partition("=")
                env.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return env


def read_input(path):
    if path in (None, "-", ""):
        return sys.stdin.read()
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def resolve_model(prov, args, env):
    if prov["name"] == "glm-audit":
        model = args.model or env.get("GLM_MODEL", prov["default_model"])
        if model in ("glm-4.7-flash", "glm-4.6v-flash", "glm-4.5-flash", "glm-4.7"):
            # 2026-08-15 事故红线（升级 2026-09-02 放行付费 glm-5.3-flash）：免费版/弃用版禁列
            print(f"GLM 事故红线：model={model} 为免费版/弃用版，强制使用 {prov['default_model']}", file=sys.stderr)
            model = prov["default_model"]
        return model
    if prov["name"] == "kimi":
        return args.model or env.get("KIMI_MODEL", prov["default_model"])
    if prov["name"] == "hunyuan-audit":
        # 兼容旧 hunyuan_audit.py：HUNYUAN_MODEL 环境变量可覆盖默认 hy3
        return args.model or env.get("HUNYUAN_MODEL", prov["default_model"])
    return args.model or prov["default_model"]


class StreamResult:
    """一次流式请求的累计结果。"""
    def __init__(self):
        self.content = ""
        self.reasoning = ""
        self.finish_reason = None
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        self.ttft = None          # 首 chunk 秒
        self.wait_s = 0
        self.saw_any = False      # 是否收到过任何 chunk（首 token 判定）
        self.done_seen = False


def atomic_progress(path, data):
    """进度文件原子写：临时文件 + os.rename（定稿附注闭合项 2/验收 P2）。"""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.rename(tmp, path)


def _parse_data_line(res, line, t0, tcfg, progress_file, last_progress):
    """解析单条 SSE data 行（2026-08-31 提取：EOF 残片与流内行共用）。返回 last_progress。"""
    payload = line[5:].strip()
    if payload == "[DONE]":
        res.done_seen = True
        return last_progress
    try:
        obj = json.loads(payload)
    except json.JSONDecodeError:
        return last_progress
    ch = (obj.get("choices") or [None])[0]
    if isinstance(ch, dict):
        delta = ch.get("delta") or {}
        c = delta.get("content")
        r = delta.get("reasoning_content")
        if c:
            res.content += c
        if r:
            res.reasoning += r
        if not res.saw_any and (c or r):
            res.saw_any = True
            res.ttft = time.time() - t0
        if ch.get("finish_reason"):
            res.finish_reason = ch["finish_reason"]
    if obj.get("usage"):
        u = obj["usage"]
        res.usage["prompt_tokens"] = u.get("prompt_tokens", 0) or res.usage["prompt_tokens"]
        res.usage["completion_tokens"] = u.get("completion_tokens", 0) or res.usage["completion_tokens"]
        res.usage["total_tokens"] = u.get("total_tokens", 0) or res.usage["total_tokens"]
    # 时长/心跳检查（每 chunk 后）
    now = time.time()
    res.wait_s = now - t0
    if not res.saw_any and res.wait_s > tcfg["ttft"]:
        raise BridgeError(13, "gateway_silent",
                          f"网关未响应：ttft {tcfg['ttft']}s 窗口内无首 chunk")
    if res.wait_s > tcfg["max_duration"]:
        raise BridgeError(18, "duration_exceeded",
                          f"超总时长上限 {tcfg['max_duration']}s")
    # 进度文件原子写（每 10s 或每 10 chunk）
    if progress_file and (res.wait_s - last_progress >= 10 or
                          (res.saw_any and res.wait_s - last_progress >= 2 and int(res.wait_s) % 10 == 0)):
        atomic_progress(progress_file, {
            "tokens": len(res.content) + len(res.reasoning),
            "wait_s": round(res.wait_s, 1),
            "ttft_s": round(res.ttft or 0, 1),
        })
        last_progress = res.wait_s
    return last_progress


def _read_chunked_block(resp):
    """手动解 chunked（MiniMax 实测 2026-08-31）。

    http.client 的 _read_chunked/_safe_read 内部用 fp.read(n)（阻塞读满 n 字节，
    慢流卡死）；_safe_readinto 在 Python 3.14 触发 readline-on-None。改用
    fp.readline（读到 \\n 即返，不等待填满）+ fp.read1（至多一次底层读取）自解。
    返回解码后的一块数据；b"" = 流结束。
    """
    while True:
        line = resp.fp.readline()
        if not line:
            return b""  # EOF
        size_line = line.strip()
        if not size_line:
            continue
        try:
            size = int(size_line.split(b";")[0], 16)
        except ValueError:
            return b""  # 协议失步：按流结束处理
        if size == 0:
            resp.fp.readline()  # 读尾部 CRLF
            return b""
        data = b""
        while len(data) < size:
            blk = resp.fp.read1(size - len(data))
            if not blk:
                return data  # 异常 EOF：返回已收部分
            data += blk
        resp.fp.readline()  # 读 chunk 尾部 CRLF
        return data


def call_once(prov, key, messages, max_tokens, tcfg, progress_file=None, start_total=None,
              role_hint=""):
    """单次流式请求。返回 StreamResult；失败抛 BridgeError。

    tcfg: {"ttft": N, "heartbeat": N, "max_duration": N}（秒）
    超时语义：socket timeout = max(ttft, heartbeat)；ttft/max_duration 用时间戳判定；
    socket.timeout 且未收首 chunk → 13（gateway_silent）；已收 → 17（heartbeat_dead）。
    """
    body = {
        "model": max_tokens.get("_model"),
        "messages": messages,
        "max_tokens": max_tokens["value"],
        "stream": True,
        "temperature": 1.0,
    }
    if prov["name"] == "kimi":
        # Moonshot 流式默认不返回 usage；需 stream_options.include_usage
        # （成本铁律逐笔记账依赖 usage，2026-08-31 实测补）
        body["stream_options"] = {"include_usage": True}
    req = urllib.request.Request(
        os.environ.get("BRIDGE_BASE_URL") or prov["url"],
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    res = StreamResult()
    _CURRENT["res"] = res
    t0 = time.time()
    deadline = t0 + tcfg["max_duration"]
    sock_to = max(tcfg["ttft"], tcfg["heartbeat"])
    try:
        with urllib.request.urlopen(req, timeout=sock_to) as resp:
            buf = b""
            last_progress = 0
            while True:
                try:
                    # Python 3.14 http.client: read(n)/readinto(b) 经 BufferedReader
                    # 会阻塞到读满 n 字节（除非 EOF）——SSE 流 chunk 只有几十字节，
                    # 读满 4096 永远等不到 → 卡死到 socket 超时。
                    # 非 chunked 用 read1()；chunked（MiniMax）手动解码（见
                    # _read_chunked_block）——fp.read1 读原始 chunked 流会把
                    # chunk size 行混入 SSE 行导致 JSON 解析失败。
                    if resp.chunked:
                        blk = _read_chunked_block(resp)
                    else:
                        blk = resp.fp.read1(4096)
                except socket_timeout():
                    # socket 读超时：按是否已收首 chunk 分类
                    if not res.saw_any:
                        raise BridgeError(13, "gateway_silent",
                                          f"网关未响应：{tcfg['ttft']}s 窗口内无首 chunk")
                    raise BridgeError(17, "heartbeat_dead",
                                      f"流卡死：超过心跳阈值 {tcfg['heartbeat']}s 无新内容")
                if not blk:
                    break
                buf += blk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    line = line.decode("utf-8", errors="replace").strip().strip("\r")
                    if not line.startswith("data:"):
                        continue  # 注释行/空行/keep-alive 跳过
                    last_progress = _parse_data_line(res, line, t0, tcfg, progress_file, last_progress)
                    if res.done_seen:
                        break
            # EOF：处理 buf 残片——最后一个 data 行可能被 TCP 段边界切掉行尾 \n
            #（2026-08-31 实测：MiniMax 长流最后 usage chunk 残片丢失 → usage=0）
            if buf and not res.done_seen:
                line = buf.decode("utf-8", errors="replace").strip().strip("\r")
                if line.startswith("data:"):
                    _parse_data_line(res, line, t0, tcfg, progress_file, last_progress)
            # 流结束判定：MiniMax 等厂商流内直接带 finish_reason/usage 且不发送
            # [DONE]（七厂商映射表实测，2026-08-31）；无 [DONE] 但已收完整信号 =
            # 正常结束；否则判流中断。
            if not res.done_seen and res.saw_any and not res.finish_reason and not res.usage["total_tokens"]:
                raise BridgeError(14, "network_error", "流中断：EOF 提前结束（未收到 [DONE] 且无完成信号）")
    except urllib.error.HTTPError as e:
        if e.code == 429:
            raise BridgeError(11, "rate_limited", "限流（HTTP 429）")
        if e.code in (401, 402, 403):
            raise BridgeError(12, "auth_quota", f"认证/费用问题（HTTP {e.code}）")
        raise BridgeError(14, "network_error", f"HTTP {e.code}: {e.read().decode(errors='replace')[:200]}")
    except urllib.error.URLError as e:
        raise BridgeError(14, "network_error", f"网络错误: {e.reason}")
    except BridgeError:
        raise
    except Exception as e:
        raise BridgeError(14, "network_error", f"异常: {e}")
    # finish_reason 回退判定（映射表：无 finish_reason → usage 判定）
    if not res.finish_reason and res.usage["completion_tokens"] >= max_tokens["value"]:
        res.finish_reason = "length"
    elif not res.finish_reason:
        res.finish_reason = "stop"
    return res


def socket_timeout():
    import socket
    return socket.timeout


def audit_once(prov, key, messages, mt, tcfg, progress_file):
    """首 token 前失败整请求重试 1 次；首 token 后不整请求重试（定稿 P6）。"""
    try:
        return call_once(prov, key, messages, mt, tcfg, progress_file)
    except BridgeError as e:
        if e.fail_class in ("network_error", "gateway_silent") and not e.msg.startswith("流中断"):
            # 首 token 前失败（网关未响应/网络错误）：重试 1 次
            return call_once(prov, key, messages, mt, tcfg, progress_file)
        raise


def continue_request(res, messages, prov, key, mt, tcfg, progress_file):
    """截断自愈：续写（assistant 续聊或全新请求），max_tokens 前次×2 封顶（闭合项 3）。"""
    next_mt = {"value": min(mt["value"] * 2, CONTINUE_CAP)}
    if res.content:
        msgs = list(messages) + [{"role": "assistant", "content": res.content},
                                 {"role": "user", "content": "继续输出未完成的部分，直接从断点继续，不要重复已写内容。"}]
    else:
        # reasoning 截断且 content 为空：全新请求（reasoning_content 不可回传）
        msgs = list(messages)
        next_mt["value"] = min(mt["value"] * 2, CONTINUE_CAP)
    return call_once(prov, key, msgs, next_mt, tcfg, progress_file), msgs


def run_audit(cli_name, args, env):
    _CURRENT["out"] = args.out  # SIGTERM flush 落盘目标
    prov = dict(PROVIDERS[cli_name])
    prov["name"] = cli_name
    key = env.get(prov["key"], "")
    if not key:
        print(f"{cli_name}: {prov['key']} 未配置", file=sys.stderr)
        sys.exit(1)
    model = resolve_model(prov, args, env)
    material = read_input(args.artifact)
    focus = args.focus or "常规对抗审计"
    # ---- cost-opt B1：seat_class 分流 + 压缩管线（Q-EX0）----
    try:
        payload, bmeta = _build_compressed_payload(cli_name, args, material)
    except ValueError as e:
        print(f"{cli_name}: {e}", file=sys.stderr)
        return 2
    # ---- cost-opt B2：增量模式留痕（修正轮材料须已含压缩全文+diff+摘要头）----
    if args.incremental:
        bmeta["round"] = "incremental"
        if "【压缩输入 B1】" not in payload:
            print(f"{cli_name}: [B2] 增量模式材料缺压缩头部（B1 校验），继续但留痕 warning", file=sys.stderr)
            bmeta["incremental_warn"] = True
    # 缓存友好：材料前置 + focus 后置（前缀稳定 → 命中缓存）
    user = f"【待审材料】\n{payload}\n\n【审计重点】{focus}"
    _base_system = args.system or SYSTEM
    if not args.system:  # 显式 --system 保留自定义权（长输出等特殊场景）
        _base_system = _build_system_prompt(_base_system)
    messages = [{"role": "system", "content": _base_system},
                {"role": "user", "content": user}]
    print(f"{cli_name}: [B1] seat_class={bmeta.get('seat_class')} "
          f"compressed={bmeta.get('compressed')} ratio={bmeta.get('ratio', '-')} "
          f"sha256={bmeta.get('sha256', '-')} full_path={bmeta.get('full_path', '-')}",
          file=sys.stderr)
    mt = {"value": args.max_tokens or MAX_TOKENS_DEFAULT.get(cli_name, 16384), "_model": model}
    tcfg = {"ttft": args.ttft, "heartbeat": args.heartbeat,
            "max_duration": args.max_duration or LONG_TASK_SEATS.get(cli_name, DEFAULTS["max_duration"])}

    # 429 退避重试（外层；限流后指数退避）
    retries = 0
    fail = None
    while True:
        try:
            res = audit_once(prov, key, messages, mt, tcfg, args.progress_file)
            break
        except BridgeError as e:
            if e.fail_class == "rate_limited" and retries < 3:
                retries += 1
                delay = [10, 30, 60][retries - 1]
                print(f"{cli_name}: 限流退避重试 {retries}/3，{delay}s 后重试", file=sys.stderr)
                time.sleep(delay)
                continue
            fail = e
            break

    if fail:
        _write_exit_code(args.out, fail.code, fail.fail_class)
        if args.json:
            print(json.dumps({"content": "", "usage": {"prompt_tokens": 0, "completion_tokens": 0,
                              "total_tokens": 0}, "usage_calls": 0, "finish_reason": None,
                              "ttft_s": 0, "wait_s": 0, "fail_class": fail.fail_class},
                             ensure_ascii=False))
        print(f"{cli_name}: {fail.msg}", file=sys.stderr)
        return fail.code

    # 截断自愈（≤2 次）
    usage_calls = 1
    merged = res
    merged.usage["prompt_tokens"] = res.usage["prompt_tokens"]
    merged.usage["completion_tokens"] = res.usage["completion_tokens"]
    merged.usage["total_tokens"] = res.usage["total_tokens"]
    attempt = 0
    while merged.finish_reason == "length" and attempt < 2:
        attempt += 1
        print(f"{cli_name}: 检测到输出截断（length），自动续写 {attempt}/2", file=sys.stderr)
        try:
            nxt, _ = continue_request(merged, messages, prov, key, mt, tcfg, args.progress_file)
        except BridgeError as e:
            if e.fail_class == "rate_limited":
                print(f"{cli_name}: 续写遇限流，保留已完成部分（{len(merged.content)} 字符）", file=sys.stderr)
                break
            print(f"{cli_name}: 续写失败（{e.fail_class}），保留已完成部分", file=sys.stderr)
            break
        merged.content += nxt.content
        merged.reasoning += nxt.reasoning
        merged.finish_reason = nxt.finish_reason
        merged.wait_s += nxt.wait_s
        for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
            merged.usage[k] = merged.usage.get(k, 0) + nxt.usage.get(k, 0)
        usage_calls += 1

    content = merged.content.strip() or merged.reasoning.strip()
    truncated = merged.finish_reason == "length"
    if truncated and args.out:
        # 15 仅在自愈后仍截断；已完成部分仍落盘不丢弃
        print(f"{cli_name}: 输出仍截断（自愈 {attempt} 次后），已完成 {len(merged.content)} 字符",
              file=sys.stderr)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(merged.content or "")
    if args.json:
        print(json.dumps({
            "content": merged.content or "",
            "usage": {"prompt_tokens": merged.usage.get("prompt_tokens", 0),
                      "completion_tokens": merged.usage.get("completion_tokens", 0),
                      "total_tokens": merged.usage.get("total_tokens", 0)},
            "usage_calls": usage_calls,
            "finish_reason": merged.finish_reason,
            "ttft_s": round(merged.ttft or 0, 1),
            "wait_s": round(merged.wait_s, 1),
            "fail_class": "truncated" if truncated else "ok",
        }, ensure_ascii=False))
    else:
        print(merged.content or merged.reasoning or "")
        print(f"[bridge] model={model} finish={merged.finish_reason} usage={json.dumps(merged.usage)} "
              f"calls={usage_calls} ttft={round(merged.ttft or 0,1)}s wait={round(merged.wait_s,1)}s",
              file=sys.stderr)
    _write_exit_code(args.out, 15 if truncated else 0, "truncated" if truncated else "ok")
    return 15 if truncated else 0


def _write_exit_code(out_path, code, fail_class):
    """退出码落盘（watchdog 跨进程判定用；2026-08-31 dsh-audit 配套）。"""
    if not out_path:
        return
    try:
        with open(out_path + ".exit_code", "w", encoding="utf-8") as f:
            f.write(f"{code} {fail_class}\n")
    except OSError:
        pass


def audit_main(cli_name, argv):
    """薄封装可复用的审计入口：解析 argv（不含 program name）并执行。返回退出码。"""
    signal.signal(signal.SIGTERM, _sigterm_handler)
    if cli_name not in PROVIDERS:
        print(f"未知 CLI 名: {cli_name}（可用：{', '.join(sorted(PROVIDERS))}）", file=sys.stderr)
        return 2
    ap = argparse.ArgumentParser(prog=cli_name, description="三审九方统一桥接内核 bridge_core")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("audit", help="对抗审计/裁决")
    p.add_argument("artifact", nargs="?", default="-")
    p.add_argument("focus", nargs="?", default="")
    p.add_argument("--json", action="store_true")
    p.add_argument("--model", default="")
    p.add_argument("--system", default=None)
    p.add_argument("--out", default=None, help="输出落盘路径")
    p.add_argument("--progress-file", default=None, help="进度文件（原子写）")
    p.add_argument("--ttft", type=int, default=DEFAULTS["ttft"], help="首 chunk 等待窗口（秒）")
    p.add_argument("--heartbeat", type=int, default=DEFAULTS["heartbeat"], help="chunk 心跳阈值（秒）")
    p.add_argument("--max-duration", type=int, default=0,
                   help="总时长上限（秒）；0=按席位默认（三审 7200/其余 1800）")
    p.add_argument("--max-tokens", type=int, default=0, help="输出上限；0=按席位默认")
    # ---- cost-opt B1/B2（2026-09-01）：seat_class 分流 + 压缩管线 ----
    # Q-EX0 硬约束（三审对抗 Qwen 终裁）：对抗/裁决/终审席禁止有损压缩；仅承办/辅助类可压缩
    p.add_argument("--seat-class", default=None,
                   help="调用席类：lead|aux（可压缩）/adversary|judge|final（硬编码禁压缩）。"
                        "缺省按 CLI 名硬编码映射；显式值仅允许从禁压缩类再确认（不可将禁压缩类改为可压缩）")
    p.add_argument("--no-compress", action="store_true", help="承办/辅助类显式豁免压缩（留痕）")
    p.add_argument("--incremental", action="store_true",
                   help="修正轮增量模式：材料须已含[压缩全文+diff+摘要头]，仅校验留痕（round≥2）")
    p.add_argument("--crg", default=None,
                   help="demo：code-review-graph 定向裁剪（repo 路径），需 --crg-focus 焦点文件")
    p.add_argument("--crg-focus", default=None, help="--crg 焦点文件（相对 repo）")
    try:
        args = ap.parse_args(argv)
    except SystemExit:
        return 2
    if args.cmd != "audit":
        return 2
    env = load_env()
    return run_audit(cli_name, args, env)


def main():
    name = os.environ.get("BRIDGE_CLI_NAME") or os.path.basename(sys.argv[0])
    return audit_main(name, sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
