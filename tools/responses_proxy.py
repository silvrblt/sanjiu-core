#!/usr/bin/env python3
"""responses_proxy.py — codex(responses 协议) → 智谱(chat 协议) 轻量适配代理
用途：codex CLI 执行引擎切 glm-5.3-flash（老板 T1 2026-09-02；codex wire_api 仅支持 responses，智谱仅 chat）
监听 127.0.0.1:8787；POST /v1/responses → 转发 chat/completions（流式/非流式 + tool_calls 双向转换）
零依赖（stdlib）。日志 → stdout（launchd 落盘）。
"""
import json
import os
import time
import uuid
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UPSTREAM = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
PORT = int(os.environ.get("RSPROXY_PORT", "8787"))
LOG = print


def log(*a):
    LOG(f"[rsproxy {time.strftime('%H:%M:%S')}]", *a, flush=True)


# ---------- 请求转换：responses → chat ----------

def conv_request(body):
    msgs = []
    if body.get("instructions"):
        msgs.append({"role": "system", "content": body["instructions"]})
    inp = body.get("input")
    if isinstance(inp, str):
        msgs.append({"role": "user", "content": inp})
    elif isinstance(inp, list):
        for item in inp:
            t = item.get("type")
            if t == "function_call_output":
                msgs.append({"role": "tool", "tool_call_id": item.get("call_id", ""),
                             "content": item.get("output", "")})
                continue
            if t == "function_call":
                # 历史中的 function_call（assistant 发起的）→ assistant tool_calls（智谱要求 content 非空串）
                msgs.append({"role": "assistant", "content": "",
                             "tool_calls": [{"id": item.get("call_id", "call_" + uuid.uuid4().hex[:8]),
                                             "type": "function",
                                             "function": {"name": item.get("name", ""),
                                                          "arguments": item.get("arguments", "{}")}}]})
                continue
            role = item.get("role", "user")
            if role == "developer":
                role = "system"  # codex 用 OpenAI 新规范 developer 角色；智谱只认 system/user/assistant/tool
            content = item.get("content")
            if isinstance(content, list):
                text = "\n".join(c.get("text", "") for c in content if isinstance(c, dict))
            else:
                text = content if isinstance(content, str) else ""
            msgs.append({"role": role, "content": text})
    tools = None
    if body.get("tools"):
        tools = []
        for t in body["tools"]:
            if t.get("type") == "function":
                tools.append({"type": "function", "function": {
                    "name": t.get("name", ""), "description": t.get("description", ""),
                    "parameters": t.get("parameters") or {"type": "object", "properties": {}}}})
            # 非 function 类型（web_search 等）跳过：智谱 chat 无对应
    out = {"model": body.get("model", "glm-5.3-flash"), "messages": msgs, "stream": bool(body.get("stream"))}
    if body.get("max_output_tokens"):
        out["max_tokens"] = int(body["max_output_tokens"])
    if body.get("temperature") is not None:
        out["temperature"] = body["temperature"]
    if tools:
        out["tools"] = tools
    return out


def upstream_call(chat_body, api_key, stream=False):
    req = urllib.request.Request(UPSTREAM, data=json.dumps(chat_body).encode(),
                                 headers={"Content-Type": "application/json",
                                          "Authorization": f"Bearer {api_key}"})
    return urllib.request.urlopen(req, timeout=600)


# ---------- 响应转换 ----------

def resp_id():
    return "resp_" + uuid.uuid4().hex[:24]


def usage_map(u):
    return {
        "input_tokens": u.get("prompt_tokens", 0),
        "output_tokens": u.get("completion_tokens", 0),
        "input_tokens_details": {"cached_tokens": u.get("prompt_cache_hit_tokens", 0) or 0},
        "output_tokens_details": {"reasoning_tokens": (u.get("completion_tokens_details") or {}).get("reasoning_tokens", 0) or 0},
        "total_tokens": u.get("total_tokens", 0),
    }


def chat_to_response(chat_resp, rid, model):
    """非流式 chat 响应 → responses 对象"""
    ch = (chat_resp.get("choices") or [{}])[0]
    msg = ch.get("message") or {}
    output = []
    txt = msg.get("content") or ""
    if txt:
        output.append({"type": "message", "id": "msg_" + uuid.uuid4().hex[:16], "role": "assistant",
                       "status": "completed", "content": [{"type": "output_text", "text": txt, "annotations": []}]})
    for tc in msg.get("tool_calls") or []:
        f = tc.get("function") or {}
        output.append({"type": "function_call", "id": "fc_" + uuid.uuid4().hex[:16],
                       "call_id": tc.get("id", "call_" + uuid.uuid4().hex[:8]),
                       "name": f.get("name", ""), "arguments": f.get("arguments", "{}"), "status": "completed"})
    return {"id": rid, "object": "response", "created_at": int(time.time()), "status": "completed",
            "model": model, "output": output, "parallel_tool_calls": True,
            "usage": usage_map(chat_resp.get("usage") or {}), "error": None}


def sse(event, data):
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass  # 静默默认访问日志

    def _api_key(self):
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer ") and len(auth) > 20:
            return auth[7:]
        return os.environ.get("GLM_API_KEY", "")

    def do_POST(self):
        if not self.path.endswith("/responses"):
            self.send_error(404, "only /v1/responses")
            return
        try:
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception as e:
            self.send_error(400, f"bad json: {e}")
            return
        api_key = self._api_key()
        if not api_key:
            self.send_error(401, "GLM_API_KEY missing")
            return
        chat_body = conv_request(body)
        if os.environ.get("RSPROXY_DUMP"):
            with open("/tmp/rsproxy-last-request.json", "w") as f:
                json.dump({"raw": body, "chat": chat_body}, f, ensure_ascii=False, indent=1)
        rid = resp_id()
        model = chat_body["model"]
        log(f"{body.get('model')} stream={chat_body['stream']} msgs={len(chat_body['messages'])}")
        try:
            up = upstream_call(chat_body, api_key, chat_body["stream"])
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:400]
            log(f"upstream HTTP {e.code}: {detail}")
            self._send_json_error(e)
            return
        except Exception as e:
            self._send_json_error(e)
            return
        if chat_body["stream"]:
            self._stream_response(up, rid, model)
        else:
            try:
                chat_resp = json.loads(up.read())
                self._send_json(chat_to_response(chat_resp, rid, model))
            except Exception as e:
                self._send_json_error(e)

    def _send_json(self, obj):
        data = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_json_error(self, e):
        log("upstream error:", e)
        obj = {"error": {"code": "upstream_error", "message": str(e)[:300]}}
        self._send_json(obj)

    # ---- 流式：chat SSE → responses SSE ----
    def _stream_response(self, up, rid, model):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        def emit(event, data):
            self.wfile.write(sse(event, data))

        base = {"id": rid, "object": "response", "created_at": int(time.time()),
                "model": model, "status": "in_progress", "output": [], "error": None}
        emit("response.created", {"type": "response.created", "response": base, "sequence_number": 0})
        msg_id = "msg_" + uuid.uuid4().hex[:16]
        text_buf = []
        # tool_calls 聚合：index → {id, name, args}
        tcalls = {}
        seq = 1
        usage = None
        try:
            for raw in up:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                try:
                    chunk = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                if chunk.get("usage"):
                    usage = chunk["usage"]
                ch = (chunk.get("choices") or [{}])[0]
                delta = ch.get("delta") or {}
                if delta.get("content"):
                    if not text_buf:
                        emit("response.output_item.added",
                             {"type": "response.output_item.added", "output_index": 0, "sequence_number": seq,
                              "item": {"type": "message", "id": msg_id, "role": "assistant", "status": "in_progress",
                                       "content": []}})
                        seq += 1
                        emit("response.content_part.added",
                             {"type": "response.content_part.added", "item_id": msg_id, "output_index": 0,
                              "content_index": 0, "sequence_number": seq,
                              "part": {"type": "output_text", "text": "", "annotations": []}})
                        seq += 1
                    text_buf.append(delta["content"])
                    emit("response.output_text.delta",
                         {"type": "response.output_text.delta", "item_id": msg_id, "output_index": 0,
                          "content_index": 0, "sequence_number": seq, "delta": delta["content"], "logprobs": []})
                    seq += 1
                for tc in delta.get("tool_calls") or []:
                    idx = tc.get("index", 0)
                    slot = tcalls.setdefault(idx, {"id": tc.get("id") or f"call_{uuid.uuid4().hex[:8]}",
                                                   "name": "", "args": ""})
                    if tc.get("id"):
                        slot["id"] = tc["id"]
                    fn = tc.get("function") or {}
                    if fn.get("name"):
                        slot["name"] += fn["name"]
                    if fn.get("arguments"):
                        slot["args"] += fn["arguments"]
            # 收尾 items
            output = []
            if text_buf:
                output.append({"type": "message", "id": msg_id, "role": "assistant", "status": "completed",
                               "content": [{"type": "output_text", "text": "".join(text_buf), "annotations": []}]})
            for idx in sorted(tcalls):
                s = tcalls[idx]
                item = {"type": "function_call", "id": "fc_" + uuid.uuid4().hex[:16], "call_id": s["id"],
                        "name": s["name"], "arguments": s["args"] or "{}", "status": "completed"}
                output.append(item)
            final = dict(base, status="completed", output=output,
                         usage=usage_map(usage or {}))
            for i, item in enumerate(output):
                emit("response.output_item.done", {"type": "response.output_item.done",
                                                   "output_index": i, "sequence_number": seq, "item": item})
                seq += 1
            emit("response.completed", {"type": "response.completed", "response": final, "sequence_number": seq})
            log(f"done: text={len(''.join(text_buf))}ch tool_calls={len(tcalls)} usage={usage and usage.get('total_tokens')}")
        except (BrokenPipeError, ConnectionResetError):
            log("client disconnected")
        finally:
            try:
                up.close()
            except Exception:
                pass


def main():
    key = os.environ.get("GLM_API_KEY", "")
    if not key:
        log("FATAL: GLM_API_KEY 未设置")
        raise SystemExit(1)
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    log(f"responses→chat 代理已启动 :{PORT} → open.bigmodel.cn（glm-5.3-flash 等）")
    srv.serve_forever()


if __name__ == "__main__":
    main()
