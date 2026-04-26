# CCB 版本对比报告: v6.0.4 → v6.0.12

> 对比日期: 2026-04-25  
> 对比版本: v6.0.4 (本地) vs v6.0.12 (上游最新)

---

## 1. 概览

| 项目 | v6.0.4 | v6.0.12 |
|------|--------|---------|
| 发布日期 | 2026-04-17 | 2026-04-25 |
| Git Commit | fd920aa | f29f6d7 |
| 变更文件数 | - | 302 |
| 提交数量 | - | 约 280+ commits |

---

## 2. 版本发布时间线

| 版本 | 主要内容 |
|------|----------|
| v6.0.5 | runtime line 集成 |
| v6.0.6 | 优化发布 |
| v6.0.7 | CI 稳定化、macOS install smoke test |
| v6.0.9 | 生命周期运行时稳定化、mac 覆盖测试 |
| v6.0.10 | ccbd 启动生命周期加固 |
| v6.0.11 | tmux 后台监管就绪增强 |
| v6.0.12 | supervisor 兼容性保持 |

---

## 3. 关键变更分类

### 3.1 安全修复 (Security Fixes)

| Issue | 描述 | Commit |
|-------|------|--------|
| WebSocket 状态端点认证缺失 | websocket status endpoint lacks authentication | 57d5602 |
| X-Forwarded-For 认证绕过 | authentication bypass via trusted x-forwarded-for | f3c88dd |

**影响**: 这些是重要的安全修复，建议尽快升级。

### 3.2 平台兼容性修复

#### WSL 相关
- `e0b4b85` Fix WSL installer and tmux namespace readiness
- `5d73ddb` Fix WSL socket placement and installer staging
- `6e6a618` Fix arch-aware update smoke test

#### macOS 相关
- `c153fcc` Stabilize mac lifecycle regressions
- `2d9547b` Stabilize lifecycle runtime and add mac smoke coverage
- `8a46cd4` install: warn when Homebrew is missing on macOS

#### Windows 相关
- `7c36400` fix: strip leading slash from Windows drive letter paths
- `8be892d` fix: add missing CCB_RUN_DIR and UTF-8 encoding to Windows async script
- `1dafed9` fix: add sleep before Enter send to fix auto-submit on older WezTerm

### 3.3 生命周期与守护进程加固

这是 v6.0.5-v6.0.12 最核心的变更区域：

| 文件 | 变更说明 |
|------|----------|
| `lib/ccbd/app_runtime/lifecycle.py` | 大幅重构心跳、挂载、关闭流程 |
| `lib/ccbd/keeper_runtime/loop.py` | keeper 循环增强 |
| `lib/ccbd/services/dispatcher_runtime/shutdown.py` | 新增关闭模块 |

**关键提交**:
- `6b4cfc3` Harden ccbd startup lifecycle and legacy Python compat
- `87fce5d` Harden tmux readiness for background supervision
- `cf13c38` Preserve supervisor compatibility for background starts
- `80359cf` Separate ccbd probe timeout from operational RPCs
- `53b62dd` Restore watch timeout checks during reconnect
- `a3d4efc` Recover terminal watch results from persisted state

### 3.4 tmux 稳定性增强

- `b58ccae` Retry transient tmux server readiness during respawn
- `0568306` Retry transient tmux server exit during respawn
- `e63f3cf` Retry transient tmux respawn fork failures
- `1bdaafa` Stop post-shutdown ticks before socket cleanup
- `0e32bc9` Align phase2 socket wait timeout with startup retries
- `55e806a` fix: add automatic light/dark theme detection for tmux status bar

### 3.5 新功能 (Features)

| 功能 | 描述 | Commit |
|------|------|--------|
| 多实例 Provider 支持 | 支持同一 provider 的多个实例 | 1f4e2f7 |
| Qwen Code CLI | 新增 Qwen 作为 provider | 51676d3 |
| Tencent CodeBuddy CLI | 新增腾讯 CodeBuddy | 10d0750 |
| GitHub Copilot CLI | 新增 Copilot CLI | 6011958 |
| 外部 CCB 配置 | 减少 CLAUDE.md 上下文膨胀 | d29c096 |
| per-provider launch_args | 支持自定义启动参数和环境变量 | af5cc56 |
| tmux 自动主题检测 | 亮/暗主题自动切换 | 55e806a |

### 3.6 会话与路由修复

- `04736f5` fix: restore resume for Gemini (project name dir) and OpenCode (SQLite)
- `96debeb` fix: CWD-aware pane resolution for WezTerm multi-window routing (issue #137)
- `357e407` fix: thread caller pane ID through ask chain for cross-instance isolation
- `65c62a8` fix: add project_id suffix to pane title markers for multi-directory uniqueness
- `b7598b3` fix: handle SIGHUP to clean up processes on terminal close (issue #155)
- `46a1486` fix(core): improve ask caller routing and cross-dir session resolution

---

## 4. 核心文件变更详情

### 4.1 lifecycle.py 重构要点

```python
# 主要变更:

1. 心跳机制重构
   - 新增 _heartbeat_failures() 函数
   - refresh_heartbeat 增加 expected_pid/expected_daemon_instance_id 参数

2. 挂载生命周期
   - 新增 _mark_lifecycle_mounted() 
   - 新增 _mark_lifecycle_failed()
   - 新增 _update_startup_progress()

3. 关闭流程增强
   - 新增 release_backend_ownership() 替代直接 mark_unmounted()
   - 新增 execute_project_stop() 统一关闭流程
```

### 4.2 新增模块

| 文件 | 用途 |
|------|------|
| `lib/ccbd/services/dispatcher_runtime/shutdown.py` | 调度器关闭逻辑 |
| `lib/ccbd/app_runtime/request_guard.py` | 请求守卫 |
| `lib/ccbd/handlers/stop_all.py` | 停止所有处理器 |

### 4.3 新增文档 (Contract Documents)

| 文档 | 用途 |
|------|------|
| `docs/ccbd-lifecycle-stability-plan.md` | 生命周期稳定性计划 (907行) |
| `docs/claude-session-isolation-contract.md` | Claude 会话隔离契约 |
| `docs/codex-session-isolation-contract.md` | Codex 会话隔离契约 |
| `docs/gemini-session-isolation-contract.md` | Gemini 会话隔离契约 |
| `docs/managed-provider-completion-reliability-plan.md` | Provider 完成可靠性计划 |
| `docs/ccbd-wsl-compatibility-plan.md` | WSL 兼容性计划 |

---

## 5. 安装器变更

### install.sh
- 重构 root 检测逻辑为 `require_non_root_execution()` 函数
- 调用位置移至 main() 入口处

### 配置文件
- `config/ccb-tmux-on.sh` 大幅扩展 (+145行)
- `config/tmux-ccb.conf` 调整

---

## 6. Skills 变更

### ask SKILL.md 简化
- `a77a861` Simplify ask skills and sync Claude inherited assets
- 移除冗余内容，保持 DRY 原则

### 新增 providers
- Qwen Code CLI skills
- Tencent CodeBuddy skills
- GitHub Copilot skills

---

## 7. CI/CD 变更

- `1aa2db7` ci: drop native windows jobs
- `744bb2f` ci: stabilize cross-platform test environment
- `4d8e66f` ci: add macos install smoke test
- `f161c4c` ci: update completion hook import smoke

---

## 8. 升级风险评估

### 低风险变更
- 新增 provider 支持 (可选使用)
- tmux 主题自动检测
- 文档新增

### 中等风险变更
- 生命周期重构 (核心模块，需要充分测试)
- WSL socket 位置变更
- 心跳机制调整

### 需要关注的点
1. **lifecycle.py 大幅重构** - 这是核心守护进程模块
2. **新增多个 session isolation contract** - 可能影响现有会话行为
3. **安全修复** - 强烈建议升级

---

## 9. 升级建议

### 推荐升级路径
```bash
# 方法1: 直接更新
ccb update

# 方法2: 从源码安装
git fetch upstream
git checkout v6.0.12
./install.sh install
```

### 升级前检查
1. 备份 `.ccb/ccb.config` 配置
2. 确保没有正在运行的长时间任务
3. 记录当前工作目录的 agent 状态

### 升级后验证
```bash
# 检查版本
ccb -v

# 检查控制面板健康
ccb-ping

# 测试基本功能
ask codex "test"
```

---

## 10. 问题分析与解决方案

### 10.1 问题确认

用户反馈"用不了" v6.0.12，具体问题：**代理环境变量不生效**

- v6.0.4: 代理正常工作 ✅
- v6.0.12: 代理不工作 ❌

### 10.2 根本原因

**关键变更**: v6.0.5+ 引入了 `control_plane_env()` 函数，会**过滤掉代理环境变量**！

**文件**: `lib/runtime_env/control_plane.py` (新增)

```python
# 新版本的环境变量处理逻辑

_CONTROL_PLANE_ALLOWLIST = {
    'ANTHROPIC_API_KEY',
    'PATH',
    'HOME',
    # ... 注意：没有 HTTP_PROXY, HTTPS_PROXY, ALL_PROXY 等！
}

def control_plane_env(*, extra: dict[str, str] | None = None) -> dict[str, str]:
    env: dict[str, str] = {}
    for key, value in os.environ.items():
        if key in _CONTROL_PLANE_ALLOWLIST:
            env[key] = value
            continue
        # 只有 PYTHON/VIRTUAL_ENV/CONDA 开头的保留
        if key.startswith(('PYTHON', 'VIRTUAL_ENV', 'CONDA')):
            env[key] = value
        # ❌ 其他全部丢弃！包括代理环境变量！
    return env
```

**对比 v6.0.4 vs v6.0.12**:

| 版本 | 环境变量处理 | 代理是否继承 |
|------|-------------|-------------|
| v6.0.4 | `env = dict(os.environ)` | ✅ 继承所有 |
| v6.0.12 | `env = control_plane_env()` | ❌ 被过滤掉 |

**受影响的环境变量** (不在 allowlist 中):
- `HTTP_PROXY` / `http_proxy`
- `HTTPS_PROXY` / `https_proxy`
- `ALL_PROXY` / `all_proxy`
- `NO_PROXY` / `no_proxy`
- 其他自定义环境变量

### 10.3 解决方案

#### 方案一：使用 launch_env 配置 (推荐)

v6.0.5+ 提供了 `launch_env` 配置，可以显式指定环境变量：

```json
{
  "cmd": "agent1:codex; agent2:claude",
  "launch_env": {
    "codex": {
      "HTTP_PROXY": "http://127.0.0.1:7890",
      "HTTPS_PROXY": "http://127.0.0.1:7890",
      "ALL_PROXY": "socks5://127.0.0.1:7890"
    },
    "claude": {
      "HTTP_PROXY": "http://127.0.0.1:7890",
      "HTTPS_PROXY": "http://127.0.0.1:7890"
    }
  }
}
```

#### 方案二：修复 control_plane_env (贡献代码)

在 `_CONTROL_PLANE_ALLOWLIST` 中添加代理环境变量：

```python
_CONTROL_PLANE_ALLOWLIST = {
    # ... 现有的 ...
    'HTTP_PROXY',
    'HTTPS_PROXY',
    'ALL_PROXY',
    'NO_PROXY',
    'http_proxy',
    'https_proxy',
    'all_proxy',
    'no_proxy',
}
```

### 10.4 配置示例

#### 使用 launch_env (推荐)

```json
{
  "cmd": "agent1:codex; agent2:claude; agent3:gemini",
  "launch_env": {
    "codex": {
      "HTTP_PROXY": "http://127.0.0.1:7890",
      "HTTPS_PROXY": "http://127.0.0.1:7890",
      "ALL_PROXY": "socks5://127.0.0.1:7890"
    },
    "claude": {
      "HTTP_PROXY": "http://127.0.0.1:7890",
      "HTTPS_PROXY": "http://127.0.0.1:7890"
    },
    "gemini": {
      "HTTP_PROXY": "http://127.0.0.1:7890",
      "HTTPS_PROXY": "http://127.0.0.1:7890"
    }
  }
}
```

### 10.5 升级步骤

```bash
# 1. 备份当前配置
cp .ccb/ccb.config .ccb/ccb.config.bak

# 2. 升级到 v6.0.12
ccb update

# 或从源码升级
git fetch upstream
git checkout v6.0.12
./install.sh install

# 3. ⚠️ 重要：修改配置添加 launch_env
# 编辑 .ccb/ccb.config，添加代理环境变量

# 4. 重启 ccb
ccb kill
ccb

# 5. 验证环境变量已注入
# 在 provider 中执行: echo $HTTP_PROXY
```

### 10.6 相关代码变更

**文件**: `lib/ccbd/daemon_process.py`

```python
# v6.0.4 (旧版)
def _ccbd_env(*, keeper_pid: int | None) -> dict[str, str]:
    env = dict(os.environ)  # ✅ 直接继承所有环境变量
    env['PYTHONUNBUFFERED'] = '1'
    # ...

# v6.0.12 (新版)
def _ccbd_env(*, keeper_pid: int | None) -> dict[str, str]:
    env = control_plane_env(extra={'PYTHONUNBUFFERED': '1'})  # ❌ 过滤掉代理
    # ...
```

**文件**: `lib/runtime_env/control_plane.py` (新增)

```python
_CONTROL_PLANE_ALLOWLIST = {
    'ANTHROPIC_API_KEY',
    'PATH',
    'HOME',
    # ... ❌ 没有 HTTP_PROXY 等
}
```

### 10.7 launch_env 功能说明

| 功能 | 说明 |
|------|------|
| `launch_env` | 为指定 provider 设置环境变量 |
| `launch_args` | 为指定 provider 追加 CLI 参数 |

**支持的环境变量示例**:
- `HTTP_PROXY` / `HTTPS_PROXY` - HTTP(S) 代理
- `ALL_PROXY` - 通用代理 (支持 socks5)
- `NO_PROXY` - 排除代理的地址
- 其他自定义环境变量

### 10.8 对比：v6.0.4 vs v6.0.12

| 特性 | v6.0.4 | v6.0.12 |
|------|--------|---------|
| 环境变量继承 | ✅ 全部继承 | ⚠️ 白名单过滤 |
| 代理自动继承 | ✅ 是 | ❌ 需配置 launch_env |
| launch_env 支持 | ❌ | ✅ |
| launch_args 支持 | ❌ | ✅ |
| per-provider 环境变量 | ❌ | ✅ |

### 10.9 建议

1. **如果依赖代理**: 升级后必须在 `.ccb/ccb.config` 中配置 `launch_env`
2. **向社区反馈**: 建议在 `_CONTROL_PLANE_ALLOWLIST` 中默认添加代理环境变量
3. **临时方案**: 保持使用 v6.0.4 直到官方修复

---

## 附录: 完整提交列表 (v6.0.4..v6.0.12)

<details>
<summary>点击展开完整列表</summary>

```
ff14f11 Release 6.0.12
4c73369 Release 6.0.11
b72b7f9 Release 6.0.10
cf13c38 Preserve supervisor compatibility for background starts
87fce5d Harden tmux readiness for background supervision
acf2da3 Align kill shutdown test with runtime client semantics
80359cf Separate ccbd probe timeout from operational RPCs
6b4cfc3 Harden ccbd startup lifecycle and legacy Python compat
a77a861 Simplify ask skills and sync Claude inherited assets
52f6d95 Release 6.0.9
53b62dd Restore watch timeout checks during reconnect
a3d4efc Recover terminal watch results from persisted state
b58ccae Retry transient tmux server readiness during respawn
0568306 Retry transient tmux server exit during respawn
e63f3cf Retry transient tmux respawn fork failures
1bdaafa Stop post-shutdown ticks before socket cleanup
0e32bc9 Align phase2 socket wait timeout with startup retries
e0b4b85 Fix WSL installer and tmux namespace readiness
6e6a618 Fix arch-aware update smoke test
5d73ddb Fix WSL socket placement and installer staging
fb2093a Keep mounted lifecycle on keeper config-check errors
c153fcc Stabilize mac lifecycle regressions
cee3a6d Fix cross-platform project identity import
2d9547b Stabilize lifecycle runtime and add mac smoke coverage
... (更多提交见 git log)
```

</details>
