#!/usr/bin/env python3
"""ark_image.py — 生图 CLI（火山方舟 doubao-seedream-4.0，决策人 2026-09-03 选定主力）
用法：ark-image generate "<prompt>" -o <输出路径> [--size 1280x720] [--n 1]
零依赖（stdlib）；同步轮询取图；密钥 ARK_API_KEY。
"""
import argparse
import json
import os
import sys
import time
import urllib.request

BASE = "https://ark.cn-beijing.volces.com/api/v3"
DEFAULT_MODEL = "doubao-seedream-4-0-250828"


def gen(prompt, out, size, n, key):
    body = json.dumps({"model": DEFAULT_MODEL, "prompt": prompt, "size": size, "n": n}).encode()
    req = urllib.request.Request(f"{BASE}/images/generations", data=body,
                                 headers={"Content-Type": "application/json",
                                          "Authorization": f"Bearer {key}"})
    resp = json.loads(urllib.request.urlopen(req, timeout=120).read())
    items = resp.get("data", [])
    if not items:
        print("ERR: 无图片返回", file=sys.stderr)
        return 1
    for i, item in enumerate(items):
        url = item.get("url")
        if not url:
            continue
        target = out if len(items) == 1 else out.replace(".png", f"-{i+1}.png")
        urllib.request.urlretrieve(url, target)
        print(f"saved: {target}")
    return 0


def main():
    ap = argparse.ArgumentParser(prog="ark-image", description="生图（doubao-seedream-4.0）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate", help="文生图")
    g.add_argument("prompt")
    g.add_argument("-o", "--out", required=True)
    g.add_argument("--size", default="1280x720")
    g.add_argument("--n", type=int, default=1)
    args = ap.parse_args()
    key = os.environ.get("ARK_API_KEY", "")
    if not key:
        print("ERR: ARK_API_KEY 未设置", file=sys.stderr)
        return 1
    return gen(args.prompt, args.out, args.size, args.n, key)


if __name__ == "__main__":
    sys.exit(main())
