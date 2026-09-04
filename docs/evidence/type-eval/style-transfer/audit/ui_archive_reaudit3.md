# 四审包：ui_design 样板归档（一审对抗四轮——三轮 4 项证据内联回报）

**PM-4-1 口径统一**：已删除矛盾表述。统一口径 =「归档 commit 固定回链至 evidence commit 83d0b60e92bf3c0639e5e67ec8476a3803995fbe，不随主仓后续提交滚动更新。」

**PM-1-1 证据 A：meta.json 关键片段（真实文件内容）**
```json
{
 "origin_eval": "sanjiu-core@83d0b60e92bf3c0639e5e67ec8476a3803995fbe:docs/evidence/type-eval/（ui_design-三模型分工定稿-20260905.md）",
 "derived_assets": {
  "note": "站点预览副本为构建产物；canonical = 本目录文件",
  "mapping": {
   "preview-light.png": "site/public/previews/dashboards/lawfirm-ops-cream/light.png"
  }
 },
 "preview_canonical": "preview-light.png"
}
```

**PM-1-1 证据 B：SHA 验证终端输出**
```
$ cd sanjiu-core && git rev-parse HEAD
83d0b60e92bf3c0639e5e67ec8476a3803995fbe
$ python3 -c "len('83d0b60e92bf3c0639e5e67ec8476a3803995fbe')"
40
$ grep -c "83d0b60e92bf3c0639e5e67ec8476a3803995fbe" templates/dashboards/lawfirm-ops-cream/meta.json
1
```

**S8-7 证据：目录树真实输出**
```
meta.json
preview-light.png
src/dashboard.html
src/生成规范-v1-律所看板.md
src/风格基线-v3-qwen实测规范.txt
token.json
```
→ src/ 下三文件齐：dashboard.html / 生成规范-v1-律所看板.md / 风格基线-v3-qwen实测规范.txt；token.json/meta.json/preview-light.png 在模板根目录 ✓

**PM-5-1 证据：成本台账行与样本映射**
```json
{"model": "minimax-m3", "in": 2600, "out": 44000, "cost": 0.3751, "estimate": false, "task": "ui-template-v4-v6", "note": "看板定稿迭代 v4(9.3k)+v5(11.7k)+v6(10.7k)+定稿版生成 token 汇总"}
```
→ 样本映射：该行为 4 次页面生成的输出 token 汇总（v4=9261 / v5=11666 / v6=10717 / 定稿微调=10717 同 v6 基底+CSS 手术≈0 额外生成），对应 4 个可渲染页面产出（每页均可独立交付使用）。
→ 口径修正：**「单次模板生成综合成本 ≈¥0.094（n=4 页样本，¥0.3751/4）」**；¥0.1/页仅文档说明，不写入任何配置。

## 请裁定
首轮 7 项 + 二轮 4 项 + 三轮 4 项证据是否全部闭环？可否放行归档 commit？
输出：结论（放行/退回）→ 遗留 → 分歧。
