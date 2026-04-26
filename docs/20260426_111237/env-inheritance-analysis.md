# CCB 环境变量继承机制分析报告

> 分析日期: 2026-04-26
> 分析版本: v6.0.4 (commit 20ebac2)

**流程图**: [env-inheritance-flow.svg](./env-inheritance-flow.svg)

## 1. 整体架构

CCB 通过 tmux pane 启动各 AI provider（Claude、Codex、Gemini 等）。环境变量并非通过 tmux 自身的环境机制传递，而是将 `export`/`unset` 语句**嵌入到启动命令字符串中**，由 shell 在 provider 启动前解释执行。

最终发往 tmux 的命令格式：

```
tmux respawn-pane -k -t %N -c /cwd /bin/bash -l -c "export KEY1=val1; unset KEY2; /path/to/provider [args]"
```

## 2. 配置入口：provider_profile

每个 agent 可以在 `ccb.config` 中声明 `provider_profile`，控制环境变量继承行为。

### 2.1 ProviderProfileSpec 模型

**文件**: `lib/provider_profiles/models.py`

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `mode` | str | `"inherit"` | 三种模式：`inherit` / `overlay` / `isolated` |
| `home` | str \| None | None | 自定义 profile 根目录 |
| `env` | dict[str, str] | `{}` | 额外注入的环境变量 |
| `inherit_api` | bool | `True` | 是否继承 API key |
| `inherit_auth` | bool | `True` | 是否继承认证文件 |
| `inherit_config` | bool | `True` | 是否继承 provider 配置 |
| `inherit_skills` | bool | `True` | 是否继承 skills 目录 |
| `inherit_commands` | bool | `True` | 是否继承 commands 目录 |

### 2.2 三种模式的行为差异

| 特性 | inherit | overlay | isolated |
|------|---------|---------|----------|
| 继承父进程环境 | 是 | 是 | 是（但 API key 会被 unset） |
| `env` 字段过滤 | 只传 API key 相关的 | 全部传递 | 全部传递 |
| API key 处理 | 保留继承的值 | 保留 + 可覆盖 | 显式 unset |
| 文件系统隔离 | 无 | 无 | Codex 会创建独立 HOME |

**关键区别在 materializer** (`lib/provider_profiles/materializer.py` 第 131-151 行)：

- `inherit` 模式：`spec.env` 中**只有 API key** 才会传递到 ResolvedProviderProfile.env
- `overlay`/`isolated` 模式：`spec.env` 中**所有 key** 都会传递

```python
# materializer.py 第 138 行
if key in api_keys or profile_spec.mode != 'inherit':
    filtered[key] = value
```

## 3. 各 Provider 的 Env 组装

### 3.1 Claude — 最完善

**关键文件**: `lib/provider_backends/claude/launcher_runtime/env_runtime/exports.py`

组装流程：
1. `collect_explicit_api_env()` — 从 `profile.env` 和 `spec.env` 收集 API key
2. `unset_api_env_parts()` — 若 `inherit_api=False`，生成 `unset` 语句清除所有 Claude API key
3. `reconcile_base_url()` — 处理 `ANTHROPIC_BASE_URL`：
   - 如果指向一个不可用的本地 TCP 端口（200ms 探测），自动丢弃
   - 否则从 `os.environ` 或 `~/.claude/settings.json` 继承

涉及的 API key：`ANTHROPIC_API_KEY`、`ANTHROPIC_AUTH_TOKEN`、`ANTHROPIC_BASE_URL`

### 3.2 Codex — 有独立 HOME 机制

**关键文件**: `lib/provider_backends/codex/launcher_runtime/command_runtime/service.py`

特殊之处：
- `isolated` 模式下会创建完全独立的 `CODEX_HOME` 目录（含 sessions/、config.toml 等）
- 根据 `inherit_config/auth/skills/commands` 决定是否从系统 `~/.codex/` 复制文件
- `_env_map()` 函数（第 76-89 行）组装完整的 env dict

优先级（低到高）：
```
profile.env → spec.env → CODEX_* 固定变量 → codex_home_overrides → CCB 上下文变量
```

### 3.3 Gemini — 较简单

**关键文件**: `lib/provider_backends/gemini/launcher_runtime/env.py`

与 Claude 类似但没有 base URL 协调逻辑。涉及的 API key：`GEMINI_API_KEY`、`GOOGLE_API_KEY`、`GOOGLE_API_BASE`、`GOOGLE_GENAI_USE_VERTEXAI`

### 3.4 Droid / OpenCode — 无 profile 支持

这两个 provider **完全不走 provider_profile 机制**，只注入 CCB 上下文变量（`CCB_CALLER_ACTOR` 等），不处理 API key 和环境变量。

## 4. API Key 注册表

**文件**: `lib/provider_profiles/materializer.py` 第 16-26 行

```python
_API_ENV_KEYS = {
    'codex':   {'OPENAI_API_KEY', 'OPENAI_BASE_URL', 'OPENAI_API_BASE',
                'OPENAI_ORG_ID', 'OPENAI_ORGANIZATION'},
    'claude':  {'ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN', 'ANTHROPIC_BASE_URL'},
    'gemini':  {'GEMINI_API_KEY', 'GOOGLE_API_KEY', 'GOOGLE_API_BASE',
                'GOOGLE_GENAI_USE_VERTEXAI'},
}
```

## 5. 默认行为（无显式配置时）

当 agent 未配置 `provider_profile` 时：

1. `ProviderProfileSpec()` 使用全部默认值：`mode="inherit"`，所有 `inherit_*` 为 True
2. Claude/Gemini 的 env prefix 为空字符串（不额外 export 也不 unset）
3. Codex 检查 `~/.codex/config.toml` 是否为合法 TOML，合法则使用系统目录，否则自动隔离
4. 所有 provider 都会收到 CCB 上下文变量

**这意味着**：默认情况下，tmux pane 中的 provider 进程会**继承 tmux server 启动时的完整环境**，加上 CCB 上下文变量。

## 6. 子进程（subprocess）的环境

与 tmux pane 不同，通过 `subprocess.Popen` 启动的进程直接用 Python 的 `os.environ.copy()` 继承：

- **ccbd daemon** (`lib/ccbd/daemon_process.py`)：完整继承 + `PYTHONUNBUFFERED`、`PYTHONPATH`
- **Codex bridge** (`lib/provider_backends/codex/launcher_runtime/bridge.py`)：完整继承 + `CODEX_*` 变量

## 7. 数据流总结

```
ccb.config
  └─ agents.<name>.env ──────────────────────┐
  └─ agents.<name>.provider_profile ─────────┤
       ├─ mode (inherit/overlay/isolated)     │
       ├─ env (额外 env)                      │
       ├─ inherit_api/auth/config/skills/...  │
       └─ home (自定义目录)                    │
                                              │
              ▼                               │
  materialize_provider_profile()              │
    → ResolvedProviderProfile                 │
    → 写入 runtime_dir/provider-profile.json  │
              │                               │
              ▼                               │
  provider.build_start_cmd()                  │
    ├─ 加载 ResolvedProviderProfile ◄─────────┘
    ├─ 构建 env prefix (export/unset)
    ├─ 构建 provider 命令
    └─ 返回完整 shell 命令字符串
              │
              ▼
  tmux respawn-pane -k -t %N <shell> -c "<env_prefix>; <command>"
              │
              ▼
  [tmux pane 内 shell 解释 export/unset，然后 exec provider]
```

## 8. 常见问题排查

### Q: 为什么 fork 后环境变量没了？

可能原因：

1. **tmux server 环境不包含你的变量** — tmux pane 继承的是 tmux server 启动时的环境，不是你当前 shell 的环境。如果你在启动 tmux 之后才 `export` 变量，pane 内看不到。
2. **provider_profile 的 mode 设置** — 如果设为 `isolated` 且 `inherit_api=False`，API key 会被显式 unset。
3. **inherit 模式下 spec.env 非 API key 被过滤** — `inherit` 模式只传 API key 相关的 env，其他 key 会被忽略。
4. **provider 本身不支持** — Droid 和 OpenCode 完全不处理 env，自定义 env 不会生效。

### Q: 如何让自定义环境变量传到 provider？

- **方案 A**: 在 agent 配置中设置 `provider_profile.mode: "overlay"`，然后在 `provider_profile.env` 或 `agents.<name>.env` 中声明变量
- **方案 B**: 在启动 CCB 之前（启动 tmux 之前）export 变量，让 tmux server 继承到
- **方案 C**: 设置 `ANTHROPIC_BASE_URL` 等变量到 `~/.claude/settings.json` 的 env 段（仅 Claude）

### Q: 如何验证？

```bash
# 检查 tmux server 的环境
tmux show-environment -g

# 检查某个 pane 实际收到的 env prefix
cat .ccb/runtime/<agent-name>/provider-profile.json

# 查看 start_cmd 的完整内容（调试模式）
CCB_DEBUG=1 ccb start
```
