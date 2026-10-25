---
name: deepseek-delegate
description: 让 Claude（主控）亲自调度接在终端 claude 上的 DeepSeek（执行模型）干活：写指令文件 → 用 ds-run.sh 无人值守启动 DeepSeek → 读回报 → git diff 抽查 → 归档。用户说"让 DeepSeek 去做 / 交给 DeepSeek / 用执行模型跑 / 按 AI 协作工作流推进"，或任务含有体力活（跑脚本、批量改文件、盘点、训练队列、写代码、git 操作）时**主动使用**：能交给 DeepSeek 的尽量交给它，主控只写指令和审核，以节省 Claude 额度；任务多且能拆成互不依赖的几块时，同时开多个 DeepSeek 并行。
---

# DeepSeek 委派（主控调度执行模型）

前提：用户的终端 `claude` 已在 `~/.claude/settings.json` 的 `env` 里配置为 DeepSeek（`ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic` 加上 `ANTHROPIC_AUTH_TOKEN` 和模型名）。
主控（你）不需要用户传话：直接用 `ds-run.sh` 以 headless 模式（`claude -p`）启动 DeepSeek，结果以 JSON 返回给你。
分工规则见本 skill 的 `references/AI协作工作流.md`：主控写指令、审核、把关；DeepSeek 照做并如实回报；用户只做授权决定。

## 默认原则：能交给 DeepSeek 的，就交给 DeepSeek

Claude 额度贵，DeepSeek 便宜，跑错了多跑几次也无所谓。所以**默认把活委派出去，主控尽量少动手**：

- **交给 DeepSeek**：跑脚本、训练、评估；批量改文件、写新代码；盘点和统计；生成图表；整理文档；git 的 add / commit / push（推送需要用户授权）；以及任何"照着说明做就行"的事。需要大段读文件才能弄清的情况，也让 DeepSeek 先读，把摘要写进回报。
- **主控自己做的只有**：理解目标、拆解任务、写指令、审核回报、做判断，以及审核所需的**少量**只读抽查（看几行 diff、核对几个关键数字）。
- **省主控额度的做法**：
  - 一轮指令里尽量多安排工作，用"失败就停"的检查点控制风险，减少来回；
  - 能拆成互不依赖的几块时，同时开多个 DeepSeek 并行做（见下文"并行"一节）；
  - 审核时只抽查最关键的几项，不要把整份输出读进上下文；
  - 返工也写成指令交给 DeepSeek，不要自己修；
  - DeepSeek 失败了，先判断是指令写得不清楚还是环境问题，改指令或修环境后让它重跑。
- **只有这些情况才由主控亲自动手**：DeepSeek 连续失败、并且确认是它能力不够的；需要只有主控才有的工具的；或者一两条命令就能做完，写指令反而更费事的。动手前用一句话告诉用户原因。

## 一次性准备（新电脑或首次使用时检查）

1. 启动器：`~/.local/bin/ds-run.sh` 存在且可执行。不存在的话，从本 skill 的 `scripts/ds-run.sh` 复制过去并 `chmod +x`（仓库里的 `install.sh` 会自动做这一步）。
2. 权限规则：`~/.claude/settings.json` 的 `permissions.allow` 里有 `"Bash(~/.local/bin/ds-run.sh:*)"`。如果没有就加上，改之前先备份。
3. 如果当前会话处于 **auto 模式**，安全分类器会拦截"创建无审批子代理"，也会拦截写启动器的操作，用户在对话里说一句"随便"不算数。需要用户**明确同意**，再用 `set_session_permission_mode` 切到 `default`（手动）模式完成准备。准备好之后，调用 `ds-run.sh` 就由上面那条 allow 规则放行。

## 每一轮的流程

1. **交接目录**：`<项目根>/_claude/`，里面放 `README.md`（从 `templates/README_交接目录.md` 复制，按项目填好根目录、环境里的坑、项目纪律）和 `history/`。
2. **快照**：项目是 git 仓库时，每轮开工前由主控执行 `git add -A && git commit`，保证这一轮可以 diff、可以退回。执行模型不做 commit / checkout / reset。
   项目还没有 git 的话，第一轮先让 DeepSeek 盘点体积、起草 `.gitignore`（参考 `templates/指令示例_盘点与gitignore.md`），主控核实后再 `git init`。
3. **写指令**：文件名 `_claude/Claude指令_<date "+%Y.%m.%d.%H.%M">.md`，模板见 `templates/指令模板.md`。要写清：绝对路径、具体命令、每一步的验收标准、失败即停的检查点、禁止事项、回报格式。回报文件名用同一个时间戳：`DeepSeek回报_<同一时间>.md`。
4. **启动**（必须后台运行，一轮可能要几分钟到半小时）：
   ```bash
   ~/.local/bin/ds-run.sh "<项目根>" "<指令文件绝对路径>" > /tmp/ds_<时间戳>.json 2>&1; echo "exit=$?"; grep -oE '"(is_error|num_turns|duration_ms)":("[^"]*"|[^,]*)' /tmp/ds_<时间戳>.json; grep -oE '"result":"[^"]{0,800}' /tmp/ds_<时间戳>.json; grep -oE '"permission_denials":\[[^]]{0,800}' /tmp/ds_<时间戳>.json
   ```
   用 `run_in_background: true` 跑，等完成通知，不要轮询。
5. **续跑或返工**：返回的 JSON 里有 `session_id`。要在同一上下文里接着做（例如修好权限后从第 2 步续跑），把补充说明作为第 2 个参数传入，并在后面加 `--resume <session_id>`。
6. **审核**（回报是 DeepSeek 的自述，不等于事实）：
   - 先看 `permission_denials`：它被拦了什么，就说明白名单缺什么；
   - 读回报，再用只读命令抽查最关键的几项：输出文件是否存在、关键数字、`git status` / `git diff --stat`，确认它没有动指令范围以外的文件；
   - 结论类的产出要独立核实。例如 `.gitignore` 不要信它自己写的对照表，而是用项目外的探针仓库实测（`git init --bare /tmp/x.git; git --git-dir=/tmp/x.git --work-tree=. ls-files --others --exclude-standard`），再统计会被收录的文件大小。
7. **收尾**：审核通过就 commit 一个快照，再把指令和回报 `mv` 进 `history/`。不通过就写一份新时间戳的返工指令，或者 `git checkout -- <文件>` 退回。
   向用户汇报时分清三类：已核实的、DeepSeek 自报但未核实的、下一步打算。

## 并行：同时开多个 DeepSeek

任务多、而且能拆成几块互不依赖的工作时，就同时开多个 DeepSeek，像开多个子代理一样。实测两个实例可以真正并发（各自约 4 秒，合计 5 秒跑完）。

**什么时候并行**：几块工作同时满足下面三条——
- 互不依赖：谁也不需要等别人的结果；
- 写的文件不重叠：每块只写自己的那组文件或目录，两块绝不改同一个文件；
- 各自能独立验收。

有先后依赖的就排成多轮，不要硬拆。只有一两步的小活也不必拆，拆开反而多写几份指令、多读几份回报。

**怎么做**：
1. 开工前照常打一个 git 快照（所有并行任务共用这一个）。
2. 每块写一份指令，同一时间戳加字母后缀：`Claude指令_<时间>_A.md`、`_B.md`……回报对应写成 `DeepSeek回报_<时间>_A.md`。
   每份指令开头写清楚**本块只允许写哪些路径**，并注明"同时还有其他 DeepSeek 在改别的文件，看到不是自己改的变动不要管，也不要还原"。
3. 在同一条 bash 里后台启动、一起等待：
   ```bash
   for x in A B C; do
     ~/.local/bin/ds-run.sh "<项目根>" "<项目根>/_claude/Claude指令_<时间>_$x.md" > /tmp/ds_<时间>_$x.json 2>&1 &
   done; wait
   for x in A B C; do echo "== $x"; grep -oE '"(is_error|num_turns)":[^,]*' /tmp/ds_<时间>_$x.json; grep -oE '"result":"[^"]{0,400}' /tmp/ds_<时间>_$x.json; done
   ```
   整条命令用 `run_in_background: true`，等完成通知。
4. 审核时多看一项：`git status` / `git diff --stat` 里每块改到的文件，都要落在它自己的允许范围内。越界的那一块退回重做；其他块不受影响，照常验收。
5. 全部通过后打一个快照，所有指令和回报一起归档。

**限制**：
- 同时最多开 **4 个**左右。开太多容易触发 DeepSeek 的 API 限流，审核压力也全堆到主控这边。
- 并行时 DeepSeek 一律不做 git 写操作（commit / push 由主控统一安排），否则多个实例会争抢 git 的 index 锁。
- 会抢同一份资源的任务（例如都要用 GPU 训练、都要写同一个缓存目录）不要并行，改成排队。

## 已知的坑

- **继承的环境变量**：在 Claude 桌面 App 里运行时，会话环境带着一堆 `CLAUDE_CODE_*` 和 host-auth 变量，子进程继承后会忽略 DeepSeek 配置，报 "Not logged in"。所以 `ds-run.sh` 先用 `env -i` 清空环境再启动。
- **代理会被一起清掉**：`env -i` 也会清掉 `HTTP(S)_PROXY`。如果用户是通过本地代理（例如 `127.0.0.1:7890`）访问 GitHub 或 DeepSeek，子进程就会连不上，报 "Connection was reset"。所以脚本会把代理变量透传。注意：Windows 的环境变量名不区分大小写，空的 `https_proxy` 会把 `HTTPS_PROXY` 覆盖掉，所以脚本只透传有值的变量，并且大小写两种写法设成同一个值。
- **Windows 的 `USER` 变量**：Windows 下没有 `$USER`，在 `set -u` 下会直接报错退出。脚本已用 `${USER:-${USERNAME:-}}` 兜底，并透传 USERPROFILE / APPDATA / SYSTEMROOT / TEMP。
- **Windows 用 PowerShell**：在 Windows 上，DeepSeek 跑命令走的是 **PowerShell** 工具而不是 Bash，所以白名单必须两套都写，否则 python 等命令会在 dontAsk 模式下被全部拒绝。
- **python 命令名**：有的机器只有 `python`，没有 `python3`（Windows 常见）。要在交接 README 里写明。
- **中文路径**：在 Windows 上，`/tmp/...` 路径传给 python 前要先用 `cygpath -w` 转换；文件列表用 NUL 分隔，按 UTF-8 解码。
- **白名单的边界**：放行了 python 就等于能跑任意代码。真正的保险是 git 快照，加上 README 里的纪律（禁止删除、禁止推送；数据和结果只新建、不覆盖）。
- **`total_cost_usd` 不是实际花费**：JSON 里这个数字是按 Anthropic 价格估算的，不代表 DeepSeek 的实际费用。

## 白名单（scripts/ds-run.sh）

- 允许：Read / Write / Edit / Glob / Grep；python；ls / cat / head / tail / wc / date；git status / diff / log（Bash 和 PowerShell 各一份）。
- 禁止：rm / Remove-Item / del、git push、sudo。其余命令在 dontAsk 模式下默认拒绝。
- 用户授权推送的那一轮：启动命令前加 `DS_ALLOW_PUSH=1`，这样只对本轮放开 git remote / push / branch。指令里要注明"用户已授权普通推送，禁止 force-push"。
- 其他额外权限（例如删除备份）：只在本轮的启动参数里加 `--allowedTools "..."`，并在指令里注明已授权。注意 `--disallowedTools` 优先级高于 allow，所以 rm 这类在 deny 名单里的命令，靠这种方式放不开，只能由主控亲自执行。
