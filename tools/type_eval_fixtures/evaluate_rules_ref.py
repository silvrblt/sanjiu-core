import re

def evaluate_rules(customer, rules):
    def tok(s):
        out, i = [], 0
        while i < len(s):
            c = s[i]
            if c.isspace():
                i += 1
            elif s.startswith(("==", "!=", ">=", "<="), i):
                out.append(s[i:i+2]); i += 2
            elif c in "()<>+-*/":
                out.append(c); i += 1
            elif c in "'\"":
                j = s.find(c, i+1); out.append(("s", s[i+1:j])); i = j+1
            elif s[i:i+3] == "and":
                out.append("and"); i += 3
            elif s[i:i+2] == "or":
                out.append("or"); i += 2
            elif s[i:i+3] == "not":
                out.append("not"); i += 3
            else:
                m = re.match(r"-?\d+(?:\.\d+)?|[A-Za-z_]\w*", s[i:])
                t = m.group()
                out.append(("n", float(t)) if "." in t else ("n", int(t)) if re.fullmatch(r"-?\d+", t) else ("f", t))
                i += len(t)
        return out

    def P(t, i):
        if t[i] == "not":
            v, i = P(t, i+1); return ("not", v), i
        if t[i] == "(":
            v, i = B(t, i+1)
            if t[i] == ")": i += 1
            return v, i
        l, i = C(t, i)
        return l, i

    def C(t, i):
        if t[i] in ("and", "or"):
            # and/or 出现在顶层的处理（递归先导）
            v, i = B(t, i)
            return v, i
        # 比较或操作数
        a, i = O(t, i)
        if i < len(t) and isinstance(t[i], str) and t[i] in ("==", "!=", ">", ">=", "<", "<="):
            op, i = t[i], i+1
            b, i = O(t, i)
            return ("cmp", a, op, b), i
        return a, i

    def O(t, i):
        # 操作数：字段/数字/字符串 或 算术(仅 action 用，cond 不出现)
        x = t[i]
        if isinstance(x, tuple) and x[0] in ("s", "n", "f"):
            return x, i+1
        raise ValueError("operand")

    def B(t, i):
        left, i = P(t, i)
        while i < len(t) and t[i] in ("and", "or"):
            op = t[i]; right, i = P(t, i+1)
            left = (op, left, right)
        return left, i

    def A(t, i):
        # 算术：+ - 优先级低于 * /
        v, i = T(t, i)
        while i < len(t) and t[i] in ("+", "-"):
            op = t[i]; r, i = T(t, i+1)
            v = (op, v, r)
        return v, i

    def T(t, i):
        v, i = F(t, i)
        while i < len(t) and t[i] in ("*", "/"):
            op = t[i]; r, i = F(t, i+1)
            v = (op, v, r)
        return v, i

    def F(t, i):
        if t[i] == "(":
            v, i = A(t, i+1); i += 1; return v, i
        x = t[i]
        if isinstance(x, tuple) and x[0] in ("n", "f"):
            return x, i+1
        raise ValueError("factor")

    def val(x, cust):
        if isinstance(x, tuple):
            if x[0] == "f":
                return cust.get(x[1])
            if x[0] in ("n", "s"):
                return x[1]
            if len(x) == 3 and isinstance(x[1], str) and x[1] not in ("and", "or", "not"):
                return x  # 不应到达
        return x

    def arith(e, cust):
        if isinstance(e, tuple):
            if e[0] == "f":
                return cust.get(e[1])
            if e[0] == "n":
                return e[1]
            if len(e) == 3 and e[0] in "+-*/":
                a, b = arith(e[1], cust), arith(e[2], cust)
                if a is None or b is None:
                    return None
                if e[0] == "+": return a + b
                if e[0] == "-": return a - b
                if e[0] == "*": return a * b
                return a / b
        return e

    def T_truth(node, cust):
        if isinstance(node, tuple):
            if node[0] == "and":
                return T_truth(node[1], cust) and T_truth(node[2], cust)
            if node[0] == "or":
                return T_truth(node[1], cust) or T_truth(node[2], cust)
            if node[0] == "not":
                return not T_truth(node[1], cust)
            if node[0] == "cmp":
                _, a, op, b = node
                a = val(a, cust); b = val(b, cust)
                if a is None or b is None:
                    return False
                if op == "==": return a == b
                if op == "!=": return a != b
                if op == "<": return a < b
                if op == ">": return a > b
                if op == "<=": return a <= b
                return a >= b
        return bool(node)

    for r in rules:
        cond = r.get("cond")
        if cond == "True":
            hit = True
        else:
            t = tok(cond)
            tree, _ = B(t, 0)
            hit = T_truth(tree, customer)
        if hit:
            pts = r["action"].get("points")
            if isinstance(pts, str):
                t2 = tok(pts)
                e, _ = A(t2, 0)
                v = arith(e, customer)
                v = int(v) if v is not None else None
            else:
                v = int(pts)
            return {"points": v}
    return None
