# deepseek-delegate

让 Claude 当"主控"、DeepSeek 当"执行"：Claude 负责想清楚、写指令、审核结果；跑命令、改文件这类体力活交给便宜又快的 DeepSeek。整个过程**不需要人在两个模型之间传话**，Claude 会自己在后台启动 DeepSeek，等它做完再审核。

这是一个 [Claude Code](https://docs.claude.com/en/docs/claude-code) skill，外加一个受白名单限制的启动脚本。

## 原理

```
Claude（主控会话）
  ├─ 写指令文件  _claude/Claude指令_<时间>.md
  ├─ ds-run.sh → claude -p（终端 claude，后端接 DeepSeek，白名单 + 无人值守）
  │                └─ 执行，写回报  _claude/DeepSeek回报_<时间>.md
  ├─ 读回报 + 只读抽查（git diff、关键数字）
  └─ 通过 → git 快照 + 归档；不通过 → 返工指令 / git 退回
```

分工规则见 [`skill/references/AI协作工作流.md`](skill/references/AI协作工作流.md)。

## 安装

### 1. 让终端 claude 接上 DeepSeek

在 `~/.claude/settings.json` 的 `env` 里配置（API key 换成你自己的，**不要提交到任何仓库**）：

```json
{
  "env": {
    "ANTHROPIC_BASE_URL": "https://api.deepseek.com/anthropic",
    "ANTHROPIC_AUTH_TOKEN": "<你的 DeepSeek API key>",
    "ANTHROPIC_MODEL": "<DeepSeek 模型名>",
    "ANTHROPIC_DEFAULT_SONNET_MODEL": "<DeepSeek 模型名>",
    "ANTHROPIC_DEFAULT_OPUS_MODEL": "<DeepSeek 模型名>",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL": "<DeepSeek 模型名>"
  }
}
```

模型名以 DeepSeek 官方文档为准。配好后在终端跑 `claude -p "你是哪个模型"`，能得到回答就说明接通了。

> 主控用的 Claude（例如 Claude 桌面 App）走自己的登录，不受这里的配置影响。`ds-run.sh` 启动子进程前会清空继承的环境变量，确保子进程读到的是这份 DeepSeek 配置。

### 2. 运行安装脚本

```bash
git clone https://github.com/WEN365-1/deepseek-delegate.git
cd deepseek-delegate
bash install.sh
```

安装脚本会做三件事（覆盖任何文件前都会先备份）：
- 把 skill 复制到 `~/.claude/skills/deepseek-delegate/`；
- 把启动器安装到 `~/.local/bin/ds-run.sh`；
- 在 `~/.claude/settings.json` 里加一条允许规则 `Bash(~/.local/bin/ds-run.sh:*)`，让主控 Claude 可以调用启动器。

Windows 上用 Git Bash 运行。

### 3. 使用

在 Claude Code 里说"这个交给 DeepSeek 做"或"按 AI 协作工作流推进"，Claude 就会按 skill 的流程走。第一次在某个项目里用时，Claude 会先建交接目录 `_claude/`，并建议先用 git 打一个快照。

## Kimi Work 版

仓库的 [`kimi/`](kimi/) 是同一委派工作流的 Kimi Work 适配版。它不依赖 Claude CLI 或 PowerShell 7，只用 Python 标准库直接调用 DeepSeek API，并保留“指令 → 执行 → 回报 → 独立抽查 → 归档”的流程。

### 1. 安装到 Kimi 项目

在项目根目录执行（Windows 可用 Git Bash）：

```bash
mkdir -p .agents/skills
cp -R /path/to/deepseek-delegate/kimi .agents/skills/deepseek-delegate
```

把 `/path/to/deepseek-delegate` 换成本仓库的实际路径。Kimi Work 会发现项目级 `deepseek-delegate` 技能。

### 2. 配置并使用

在自己的终端私密配置 `DEEPSEEK_API_KEY`，不要把密钥写进聊天、指令、回报或仓库。可选环境变量：

- `DEEPSEEK_MODEL`：默认 `deepseek-flash`；
- `DEEPSEEK_BASE_URL`：默认 `https://api.deepseek.com`。

然后在 Kimi Work 中说“让 DeepSeek 去做”“交给 DeepSeek”或“按 AI 协作工作流推进”。交接文件保存在项目的 `_kimi/deepseek/`。

也可以直接运行启动器：

```bash
python .agents/skills/deepseek-delegate/scripts/ds_run.py \
  --project "/absolute/project/path" \
  --instruction "_kimi/deepseek/Kimi指令_YYYY.MM.DD.HH.MM.md" \
  --report "_kimi/deepseek/DeepSeek回报_YYYY.MM.DD.HH.MM.md" \
  --json-output "_kimi/deepseek/DeepSeek运行_YYYY.MM.DD.HH.MM.json" \
  --timeout 240
```

默认只读且限制在项目目录内；`--write` 允许新建文件，`--allow-overwrite` 允许覆盖已有文件，`--allow-python` 允许运行项目内 Python 脚本。开放 Python 不是安全沙箱，只运行已经审查的脚本。完整规则见 [`kimi/SKILL.md`](kimi/SKILL.md)。

## 安全须知（请读）

- `ds-run.sh` 以 `dontAsk` 模式运行 DeepSeek：白名单之外的命令一律拒绝，不会弹窗询问。
  - 白名单：读写文件、`python`、`ls/cat/head/tail/wc/date`、`git status/diff/log`。
  - 禁止：`rm`、`sudo`、`git push`（推送只能在单轮里通过 `DS_ALLOW_PUSH=1` 显式放开）。
- **放行 python 就等于能跑任意代码**。白名单挡不住恶意或出错的 python 脚本，真正的保险是：
  1. 每轮开工前用 git 打快照，出问题可以退回；
  2. 交接 README 里写明的纪律（禁止删除；数据和结果只新建、不覆盖）；
  3. 主控每轮用 `git diff` 审核。
- 不要在含有敏感数据、或没有备份的目录里使用。
- 如果主控会话处于 auto 模式，Claude Code 的安全分类器可能会拦截首次的环境准备。这是正常的，需要你明确同意后在手动模式下完成。

## 已知的坑

详见 [`skill/SKILL.md`](skill/SKILL.md) 的"已知的坑"一节。比如：Windows 上 DeepSeek 走的是 PowerShell 工具而不是 Bash；Windows 没有 `$USER`；JSON 里的 `total_cost_usd` 是按 Anthropic 价格估算的，不是 DeepSeek 的实际花费。

## 许可

MIT
