---
name: deepseek-delegate
description: 让 Kimi 主控通过 DeepSeek API 委派边界明确的任务：写指令文件、前台限时运行、读取回报与真实 token 用量、独立抽查、归档。用户说“让 DeepSeek 去做”“交给 DeepSeek”“用执行模型”“按 AI 协作工作流推进”“多消耗 DeepSeek token”，或要求用 DeepSeek 批量盘点、计算、写代码、整理文档、复核结果时使用。默认能安全委派的体力活优先交给 DeepSeek，Kimi 负责拆解、判断与验收。
---

# DeepSeek 委派（Kimi Work 适配版）

通过 `scripts/ds_run.py` 调用 DeepSeek API，不依赖 Claude CLI。保留“指令—执行—回报—抽查—归档”流程；执行方不是 Kimi 的原生子 Agent，也不继承 Kimi 的工具、浏览器、技能或网络能力。

## 准备与限制

- 仅在用户自己的终端私密配置 `DEEPSEEK_API_KEY`；不得在聊天、指令、回报或运行记录中写入密钥，不得打印密钥。
- 可选环境变量：`DEEPSEEK_MODEL`（默认 `deepseek-flash`）、`DEEPSEEK_BASE_URL`（默认 `https://api.deepseek.com`）。
- 文件工具默认只读且限制在项目根目录；`.git` 和常见凭据文件不可访问。
- 当前 Kimi 工具不支持本技能所要求的后台任务方式。每轮用前台 Bash，单次总时限默认 240 秒，外层工具超时设为 300 秒；更长任务先拆小，禁止用 `&`、`run_in_background` 或常驻进程规避限制。
- 不自动执行 `git init/add/commit/push/reset/rebase`。只有用户明确要求某项 Git 操作时，才按该授权单独执行。

## 每轮流程

1. **建立交接目录**：使用 `<项目根>/_kimi/deepseek/`。首次使用时，从 `assets/templates/README_交接目录.md` 复制为其中的 `README.md` 并填写项目约定；`history/` 用于归档。
2. **写指令**：从 `assets/templates/指令模板.md` 创建 `Kimi指令_YYYY.MM.DD.HH.MM.md`。写清绝对项目根、输入文件、允许写路径、具体步骤、验收标准、失败即停点和回报格式。分工原则见 `references/AI协作工作流.md`。
3. **选择权限**：
   - 只读咨询、计算推导、盘点：不加权限参数。
   - 需要新建结果文件：加 `--write`。默认不覆盖已有文件。
   - 确需修改已有文件且用户已同意该范围：加 `--write --allow-overwrite`，指令逐项列出可覆盖路径。
   - 确需执行项目内 Python 脚本：加 `--allow-python`。这不是安全沙箱，脚本可执行任意 Python 操作；只在脚本内容已审查、用户同意执行时使用。
4. **前台启动**：在 Bash 中运行，路径按实际技能目录替换：
   ```bash
   python "<技能目录>/scripts/ds_run.py" \
     --project "<项目根绝对路径>" \
     --instruction "<项目根>/_kimi/deepseek/Kimi指令_<时间戳>.md" \
     --report "_kimi/deepseek/DeepSeek回报_<时间戳>.md" \
     --json-output "_kimi/deepseek/DeepSeek运行_<时间戳>.json" \
     --timeout 240
   ```
   将 Bash 的 `description` 写成用户能理解的简体中文，工具超时设为 300 秒。按所选权限追加参数，不要在 shell 中拼接密钥。
5. **验收**：先读 JSON 中的 `status`、`usage` 和 `tool_events`，再读回报。DeepSeek 自述不等于事实；Kimi 必须只读抽查关键文件、数字、计算结果或测试输出，并检查写入路径未越界。
6. **收尾**：通过后把本轮指令、回报、JSON 移入 `history/`；不通过则写新时间戳的返工指令。向用户区分“已核实”“DeepSeek 自报但未核实”“下一步”。

## 并行

仅当任务互不依赖、写入路径完全不重叠、可独立验收时并行，最多 4 路：

- 每路使用独立指令、回报、JSON 和字母后缀，如 `_A`、`_B`。
- 用工具平台的一次并行调用发起多个前台 Bash；不要在一条 shell 里用 `&` 后台启动。
- 每份指令注明允许写路径，并说明其他并行任务产生的改动不属于本任务，不得修改或还原。
- 共享 GPU、Abaqus 许可证、同一缓存或同一输出文件时改为串行。
- 所有 Git 写操作仍由 Kimi 在用户明确授权后统一处理。

## 审核与成本

- `usage` 是各次 API 调用返回的 token 合计；`usage_by_call` 保留逐次用量。不要把它换算成确定费用，除非已核对当时官方价格与缓存、时段计费规则。
- 优先委派：多文件盘点、重复计算、独立复算、代码或文档初稿、依据明确标准的检查。很小的一步任务不必委派。
- Kimi 保留：目标与验收标准、视觉输入理解、风险判断、关键数字抽查、最终一致性检查。
- 遇到限流、超时或失败，不紧密重试；先判断是指令、权限、环境还是模型能力问题，再拆分或安排后续重试。
