# OpenCode 最小可行补全方案 — 差距分析与实施计划

> 分析日期: 2026-04-26
> 分析版本: v6.0.4 (commit 20ebac2)

## 1. 当前状态

OpenCode 是 CCB 中的 **OPTIONAL provider**，与 Droid 同级。核心 providers 是 Claude、Codex、Gemini。

### 已实现

| 能力 | 状态 | 关键文件 |
|------|------|----------|
| Backend 注册 | ✅ | `__init__.py`, `manifest.py` |
| 启动器 (simple_tmux) | ✅ | `launcher.py` |
| 通信器 (ask_sync/async/ping) | ✅ | `comm.py`, `runtime/communicator*.py` |
| Session 发现与绑定 | ✅ | `session.py`, `session_runtime/` |
| 日志读取 (SQLite + JSON 双源) | ✅ | `runtime/log_reader_facade*.py` |
| 回复轮询 | ✅ | `runtime/reply_polling*.py` |
| 完成检测 (snapshot-based) | ✅ | `execution_runtime/polling.py` |
| 执行适配器 | ✅ | `execution.py` |
| Watchdog | ✅ | `runtime/session_runtime.py` |
| Prompt 包装 (req_id) | ✅ | `protocol.py` |
| 存储读取 | ✅ | `lib/opencode_runtime/storage.py` |

### 缺失

| 缺失项 | 影响 | 优先级 |
|--------|------|--------|
| `opencode_skills/` 目录 | agent 无法使用 ask/pend/ping 等技能 | **P0 — 必须** |
| Skill 加载器 + 注入 | prompt 中不包含技能指令，AI 不知道如何收发消息 | **P0 — 必须** |
| provider_profile env 组装 | spec.env 中的自定义变量无法传递 | **P1 — 重要** |
| API key 管理 | 无法隔离或覆盖 API key | **P1 — 重要** |

### 不做（超出最小范围）

| 项目 | 原因 |
|------|------|
| Bridge 进程 | 当前存储轮询能工作，性价比低 |
| Headless 模式 | 取决于 OpenCode 本身是否支持 |
| Session registry | 工程量大，非 MVP 必需 |
| Resume 支持 | 架构级改动 |
| 精确完成检测 | 需要修改 OpenCode 本身的输出协议 |

---

## 2. 需要改动的文件清单

### 新增文件

| 文件 | 说明 | 参照模板 |
|------|------|----------|
| `opencode_skills/ask/SKILL.md` | ask 技能定义 | `droid_skills/ask/SKILL.md` |
| `opencode_skills/pend/SKILL.md` | pend 技能定义 | `droid_skills/pend/SKILL.md` |
| `opencode_skills/ping/SKILL.md` | ping 技能定义 | `droid_skills/ping/SKILL.md` |
| `lib/provider_backends/opencode/protocol_runtime/__init__.py` | 包初始化 | — |
| `lib/provider_backends/opencode/protocol_runtime/skills.py` | Skill 加载器 | `claude/protocol_runtime/skills.py` |
| `lib/provider_backends/opencode/protocol_runtime/prompt.py` | Prompt 组装 (skill 注入) | `claude/protocol_runtime/prompt.py` |

### 修改文件

| 文件 | 改动内容 |
|------|----------|
| `lib/provider_backends/opencode/protocol.py` | 调用 prompt.py 的 skill 注入，不再简单拼接 |
| `lib/provider_backends/opencode/launcher.py` | 加载 provider_profile，组装 env prefix |
| `lib/provider_backends/opencode/manifest.py` | 更新能力声明（可选） |

### 不需要改动的文件

| 文件 | 原因 |
|------|------|
| `lib/provider_core/registry_runtime/builtin_backends.py` | OpenCode 已注册 |
| `lib/provider_core/runtime_specs.py` | 已有 OPENCODE_RUNTIME_SPEC |
| `lib/provider_backends/opencode/execution.py` | 执行逻辑完整 |
| `lib/provider_backends/opencode/comm.py` | 通信器完整 |
| `lib/provider_backends/opencode/__init__.py` | backend 组装完整 |

---

## 3. 各改动详细说明

### 3.1 创建 `opencode_skills/` 目录

参照 `droid_skills/` 的模式，创建最小技能集：

**`opencode_skills/ask/SKILL.md`** — 核心 skill，教会 OpenCode agent 如何：
- 使用 `ccb ask <agent> <message>` 发送异步消息
- 识别 `[CCB_ASYNC_SUBMITTED]` 后立即结束 turn
- 不轮询、不重试、不 sleep

内容基本复制 `droid_skills/ask/SKILL.md`，改为 "OpenCode Version"。

**`opencode_skills/pend/SKILL.md`** — 简单 pass-through：
- `/pend <agent>` → `ccb pend $ARGUMENTS`

**`opencode_skills/ping/SKILL.md`** — 简单 pass-through：
- `/ping <agent>` → `ccb ping $ARGUMENTS`

### 3.2 创建 Skill 加载器

**`lib/provider_backends/opencode/protocol_runtime/skills.py`**

参照 `claude/protocol_runtime/skills.py` 的模式：
- 从 `opencode_skills/` 目录读取 skill 文件
- 优先加载 `ask/RUNTIME.md` > `ask/SKILL.md`
- Strip YAML front matter
- 缓存结果
- 可通过 `CCB_OPENCODE_SKILLS` env var 禁用

关键差异：Claude 的加载器硬编码只加载 `ask` skill。OpenCode 可以用同样的模式。

### 3.3 创建 Prompt 组装器

**`lib/provider_backends/opencode/protocol_runtime/prompt.py`**

参照 `claude/protocol_runtime/prompt.py`：
- 加载 skills 文本
- 将 skills 文本 prepend 到用户消息前面
- 保留现有的 `CCB_REQ_ID` 标记

修改 `protocol.py` 中的 `wrap_opencode_prompt()` 调用新的 prompt 组装器。

### 3.4 增强 Launcher 的 Env 组装

**`lib/provider_backends/opencode/launcher.py`**

在 `build_start_cmd()` 中：
1. 加载 `ResolvedProviderProfile`（从 runtime_dir）
2. 构建 env prefix：
   - profile.env 中的值
   - spec.env 中的值
   - 保留现有的 CCB caller context
3. API key 处理：如果 `inherit_api=False`，unset OpenCode 相关的 API key

需要定义 OpenCode 的 API key 集合。目前 `_API_ENV_KEYS` 中没有 opencode 条目，需要添加（取决于 OpenCode 使用的 env var）。

---

## 4. 实施顺序

```
Step 1: 创建 opencode_skills/ 目录和基础 skill 文件
         ↓
Step 2: 创建 protocol_runtime/ 目录，实现 skill 加载器
         ↓
Step 3: 实现 prompt 组装器，修改 protocol.py 调用新组装器
         ↓
Step 4: 增强 launcher.py 的 env 组装
         ↓
Step 5: 测试验证
```

---

## 5. 验证方案

1. **Skill 加载测试**: 设置 `CCB_OPENCODE_SKILLS=true`，确认 skill 文本被正确加载和缓存
2. **Prompt 注入测试**: 发送一条 ask 消息到 OpenCode agent，确认 prompt 中包含 skill 指令
3. **Env 传递测试**: 在 ccb.config 中为 OpenCode agent 配置 env 字段，确认变量出现在 tmux pane 中
4. **End-to-end 测试**: 通过 OpenCode agent 执行 `ccb ask` 发消息到另一个 agent，确认完整流程
