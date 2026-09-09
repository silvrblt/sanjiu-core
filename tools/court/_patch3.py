# -*- coding: utf-8 -*-
"""BLK-3/4/6 + MAJ-3/4 + MIN-1/4 patch"""
import pathlib

p = pathlib.Path(__file__).parent / "lead_route.py"
t = p.read_text(encoding="utf-8")

# ---- BLK-3：真实循环 no-cli 分支链节点全字段 ----
old = """            cli, api_id, mt, api_src = resolve_cli(models_yaml, model, vendor)
            if not cli:
                errors.append(f"{model}: 无可用桥接 CLI（vendor={vendor}）")
                chain.append({"model": model, "ok": False, "err": "无 CLI", "api_id_source": api_src})
                continue"""
new = """            cli, api_id, mt, api_src = resolve_cli(models_yaml, model, vendor)
            if not cli:
                errors.append(f"{model}: 无可用桥接 CLI（vendor={vendor}, source={api_src}）")
                chain.append({"model": model, "cli": None, "api_id": None, "api_id_source": api_src,
                              "api_id_unverified": api_src in ("vendor_inferred", "session_seat"),
                              "ok": False, "err": "无 CLI",
                              "meta": {"fail_class": "no_cli" if api_src != "session_seat" else "session_seat"}})
                continue"""
assert old in t, "BLK-3"
t = t.replace(old, new)

# ---- BLK-4：真实链 api_id_unverified = 非池 force 或 vendor 推断 ----
old = """            chain.append({"model": model, "cli": cli, "api_id": api_id, "api_id_source": api_src,
                          "api_id_unverified": api_src == "vendor_inferred", "ok": ok,
                          "err": None if ok else content[:200], "meta": meta})"""
new = """            chain.append({"model": model, "cli": cli, "api_id": api_id, "api_id_source": api_src,
                          "api_id_unverified": (forced and not in_pool) or api_src in ("vendor_inferred", "none"),
                          "ok": ok, "err": None if ok else content[:200], "meta": meta})"""
assert old in t, "BLK-4"
t = t.replace(old, new)

# ---- BLK-6：--out 前置检查（候选调用前，exit2）----
old = """    # P0-1：真实调用必须指定 --out（产出落盘契约；dry-run 已在上方返回）
    if not out_path:
        return 2, {"decision": "manual", "task_type": ttype,
                   "note": "真实承办调用必须 --out <产出回收路径>（产出落盘契约）", "chain": chain,
                   "duration_s": round(time.time() - started, 1)}"""
new = """    # P0-1/BLK-6：真实调用 --out 前置契约检查（不浪费候选调用成本）
    if not out_path:
        return 2, {"decision": "manual", "task_type": ttype,
                   "note": "真实承办调用必须 --out <产出回收路径>（产出落盘契约）", "chain": chain,
                   "duration_s": round(time.time() - started, 1)}
    if os.path.exists(out_path) and not overwrite:
        return 2, {"decision": "manual", "task_type": ttype,
                   "note": f"产出路径已存在（{out_path}）——加 --overwrite 覆盖或更换路径", "chain": chain,
                   "duration_s": round(time.time() - started, 1)}
    out_dir = os.path.dirname(os.path.abspath(out_path)) or "."
    if not os.path.isdir(out_dir) or not os.access(out_dir, os.W_OK):
        return 2, {"decision": "manual", "task_type": ttype,
                   "note": f"产出目录不存在或不可写（{out_dir}）", "chain": chain,
                   "duration_s": round(time.time() - started, 1)}"""
assert old in t, "BLK-6"
t = t.replace(old, new)
# 移除成功分支内的 exists 检查（已前置）
old = """                try:
                    if out_path:
                        if os.path.exists(out_path) and not overwrite:  # P10：防误覆盖
                            errors.append(f"{model}: 产出路径已存在（{out_path}）——加 --overwrite 覆盖")
                            chain[-1]["err"] = "exists_no_overwrite"
                            continue
                        with open(out_path, "w", encoding="utf-8") as f:
                            f.write(content)
                except OSError as e:"""
new = """                try:
                    if out_path:
                        with open(out_path, "w", encoding="utf-8") as f:
                            f.write(content)
                except OSError as e:"""
assert old in t, "BLK-6b"
t = t.replace(old, new)

# ---- MAJ-3：session 匹配规范化（model/api_id/大小写）----
old = """    seats = models_yaml.get("seats") or {}
    # 两段式（P3）：① 目标模型命中任何 cli=session 席位 → 直接不可桥接（防同模型外部席位绕过）
    for seat in seats.values():
        if isinstance(seat, dict) and seat.get("model") == model and seat.get("cli") == "session":
            return None, None, DEFAULT_MAX_TOKENS, "session_seat"
    # ② 非 session 席位命中 → 取其 cli/api_id/max_tokens（source=seats）
    for seat in seats.values():
        if isinstance(seat, dict) and seat.get("model") == model and seat.get("cli"):
            return (seat.get("cli"), seat.get("api_id") or model,
                    seat.get("max_tokens") or DEFAULT_MAX_TOKENS, "seats")"""
new = """    seats = models_yaml.get("seats") or {}
    m_norm = str(model or "").strip().lower()
    # MAJ-3：session 匹配 = model 或 api_id 规范化（去空格/大小写不敏感）
    for seat in seats.values():
        if not isinstance(seat, dict) or seat.get("cli") != "session":
            continue
        seat_names = {str(seat.get("model") or "").strip().lower(), str(seat.get("api_id") or "").strip().lower()}
        if m_norm in seat_names:
            return None, None, DEFAULT_MAX_TOKENS, "session_seat"
    for seat in seats.values():
        if isinstance(seat, dict) and seat.get("cli"):
            seat_names = {str(seat.get("model") or "").strip().lower(), str(seat.get("api_id") or "").strip().lower()}
            if m_norm in seat_names:
                return (seat.get("cli"), seat.get("api_id") or model,
                        seat.get("max_tokens") or DEFAULT_MAX_TOKENS, "seats")"""
assert old in t, "MAJ-3"
t = t.replace(old, new)

# ---- MIN-4：dry-run 顶层 unverified 汇总 ----
old = """        return 0, {"decision": "ranked", "task_type": ttype, "model": first["model"], "cli": first["cli"],
                   "chain": chain, "out": out_path, "dry_run": True, "forced": forced, "in_pool": in_pool,
                   "duration_s": round(time.time() - started, 1)}"""
new = """        any_unv = any(c.get("api_id_unverified") for c in chain)
        return 0, {"decision": "ranked", "task_type": ttype, "model": first["model"], "cli": first["cli"],
                   "chain": chain, "out": out_path, "dry_run": True, "forced": forced, "in_pool": in_pool,
                   "selected_api_id_unverified": any_unv, "any_api_id_unverified": any_unv,
                   "duration_s": round(time.time() - started, 1)}"""
assert old in t, "MIN-4"
t = t.replace(old, new)

p.write_text(t, encoding="utf-8")
print("BLK-3/4/6 + MAJ-3 + MIN-4 patch OK")
