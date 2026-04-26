# CCB Sub-Agent 通信机制分析报告

> 分析日期: 2026-04-26
> 分析版本: v6.0.4 (commit 20ebac2)

**架构图**: [architecture-overview.svg](./architecture-overview.svg)
**时序图**: [ask-flow-sequence.svg](./ask-flow-sequence.svg)

## 1. 架构总览

CCB 实现了一个**基于文件系统的、daemon 中转的消息传递系统**。架构分五层：

```
┌─────────────────────────────────────────────────┐
│  CLI / Skill 层  (ccb ask, /ask, /pend)         │
├─────────────────────────────────────────────────┤
│  传输层  (Unix Socket RPC, JSON 协议)            │
├─────────────────────────────────────────────────┤
│  Daemon 层  (ccbd 中央调度器)                     │
├─────────────────────────────────────────────────┤
│  Mailbox 层  (per-agent 收件箱 + 租约机制)        │
├─────────────────────────────────────────────────┤
│  Provider 层  (Claude/Codex/Gemini 通信器)       │
└─────────────────────────────────────────────────┘
```

**核心理念**：每个 agent 有自己的 tmux pane，CCB 通过向 pane 内注入文本来发送消息，通过读取 provider 的 session 日志文件来接收回复。ccbd daemon 是中央调度器。

---

## 2. 传输层：Unix Socket RPC

### 2.1 连接方式

CLI 客户端通过 Unix domain socket 与 ccbd daemon 通信。

- **Socket 路径**: `.ccb/ccbd/ccbd.sock`
- **协议**: 换行分隔的 JSON RPC (`lib/ccbd/socket_client_runtime/transport.py`)

### 2.2 请求格式

```json
{ "api_version": 2, "op": "submit", "request": { ... } }
```

支持的 op：`submit`、`get`、`ack`、`inbox`、`queue`、`cancel`、`start`、`watch`、`ping`、`shutdown` 等

### 2.3 响应格式

```json
{ "api_version": 2, "ok": true, ...payload }   // 成功
{ "api_version": 2, "ok": false, "error": "..." } // 失败
```

---

## 3. Mailbox 系统

### 3.1 数据结构

三个核心模型 (`lib/mailbox_kernel/models.py`)：

**MailboxRecord** — 每个 agent 一个：
```
mailbox_id, agent_name, active_inbound_event_id,
queue_depth, pending_reply_count,
mailbox_state (IDLE/DELIVERING/BLOCKED/RECOVERING/DEGRADED)
```

**InboundEventRecord** — 收件箱中的每条事件：
```
inbound_event_id, agent_name,
event_type (TASK_REQUEST/TASK_REPLY/COMPLETION_NOTICE/RETRY_SIGNAL/...)
status (CREATED/QUEUED/DELIVERING/CONSUMED/SUPERSEDED/ABANDONED)
```

**DeliveryLease** — 投递租约，防止并发冲突：
```
agent_name, inbound_event_id, lease_version,
lease_state (ACQUIRED/RELEASED/EXPIRED/ORPHANED)
```

### 3.2 文件存储

所有数据以 JSON/JSONL 文件持久化在 `.ccb/ccbd/` 下：

| 数据 | 路径 |
|------|------|
| Agent 邮箱 | `.ccb/ccbd/mailboxes/{agent}/mailbox.json` |
| Agent 收件箱 | `.ccb/ccbd/mailboxes/{agent}/inbox.jsonl` |
| 投递租约 | `.ccb/ccbd/leases/{agent}.json` |
| 全局消息 | `.ccb/ccbd/messages/messages.jsonl` |
| 全局回复 | `.ccb/ccbd/replies/replies.jsonl` |

存储模式为 **append-only JSONL** — 追加新行记录状态变化，读取时倒序扫描取最新版本。

### 3.3 投递租约机制

防止多个进程同时向同一个 agent 投递消息：

1. `claim_next()` 查找队首可投递事件
2. `claim()` 检查冲突租约，创建 `DeliveryLease`，事件状态变为 `DELIVERING`
3. `mark_terminal()` 完成投递后释放租约，事件变为 `CONSUMED`/`ABANDONED`

---

## 4. ccbd Daemon 调度器

### 4.1 进程管理

- `ProjectKeeper` (`lib/ccbd/keeper.py`) 负责 daemon 的启动、监控和自动重启
- daemon 通过 `subprocess.Popen` 启动，继承父进程的 `os.environ`

### 4.2 Socket Server 循环

`CcbdSocketServer` (`lib/ccbd/socket_server_runtime/server.py`)：
1. 监听 Unix socket
2. 接收连接，分发请求到对应 handler
3. 定期执行 `tick` 回调驱动 job 生命周期

### 4.3 Job Dispatcher（核心）

`JobDispatcher` (`lib/ccbd/services/dispatcher.py`) 是中央调度器：

- `submit()` — 创建 JobRecord，写入目标 agent 的收件箱，启动执行
- `tick()` — 驱动生命周期：轮询活跃任务、准备回复投递
- `complete()` — 记录回复，触发回复投递回发送方

---

## 5. Provider 级通信协议

### 5.1 线路协议（Wire Protocol）

所有 provider 共享同一个标记协议 (`lib/provider_core/protocol_runtime/`)：

**发送时**（prompt wrapping）：
```
[CCB_REQ_ID: 20260426-111237-123-45678-0]

{用户的实际 prompt}

[END CCB_REQ_ID: 20260426-111237-123-45678-0]
请完成后输出: CCB_DONE:20260426-111237-123-45678-0
```

**接收时**（reply extraction）：扫描 AI 输出中的 `CCB_DONE:{req_id}` 标记来确定回复完成。

Request ID 格式：`YYYYMMDD-HHMMSS-{ms}-{pid}-{counter}`

### 5.2 Claude 通信器

`ClaudeCommunicator` (`lib/provider_backends/claude/comm_runtime/communicator_facade.py`)：

- **发送**：通过 `backend.send_text(pane_id, content)` 向 tmux pane 注入文本
- **接收**：读取 Claude 的 session 日志文件 (`~/.claude/projects/<key>/<session>.jsonl`)
- `ask_sync()` — 发送后轮询日志直到检测到 `CCB_DONE` 标记
- `ask_async()` — 发送后立即返回

### 5.3 Codex 通信器

`CodexCommunicator` (`lib/provider_backends/codex/comm_runtime/communicator_facade.py`)：

- **发送**：写入 JSON 消息到 FIFO (`comm.input_fifo`)，或回退到 tmux 文本注入
- **接收**：读取 Codex session 日志 (`~/.codex/sessions/`)
- 有 watchdog 监控 session 文件变化
- `DualBridge` 提供终端和 Codex 之间的桥接

### 5.4 Gemini 通信器

与 Claude 类似的模式：
- **发送**：tmux pane 文本注入
- **接收**：session 日志文件读取

---

## 6. 完整 Ask 流程（端到端）

以 `/ask agent2 帮我分析一下这段代码` 为例：

```
时序图：

  Agent1 (Claude)          ccbd daemon              Agent2 (Codex)
       │                        │                        │
       │  1. /ask 触发 skill    │                        │
       │  2. ccb ask agent2 ... │                        │
       │───────────────────────>│                        │
       │                        │                        │
       │                        │  3. 创建 MessageEnvelope
       │                        │  4. 创建 JobRecord     │
       │                        │  5. 写入 agent2 inbox  │
       │                        │  (TASK_REQUEST 事件)    │
       │                        │                        │
       │  [CCB_ASYNC_SUBMITTED] │                        │
       │  （CLI 立即返回）       │                        │
       │                        │                        │
       │                        │  6. tick: 执行投递      │
       │                        │  7. claim_next() 获取租约│
       │                        │───────────────────────>│
       │                        │  8. 注入 prompt 到     │
       │                        │     agent2 的 tmux pane │
       │                        │  (带 CCB_REQ_ID 标记)   │
       │                        │                        │
       │                        │                        │  9. Codex 处理请求
       │                        │                        │  10. 输出回复 +
       │                        │                        │      CCB_DONE:req_id
       │                        │                        │
       │                        │  11. tick: 检测完成     │
       │                        │  12. 提取回复文本       │
       │                        │<───────────────────────│
       │                        │                        │
       │                        │  13. 创建 ReplyRecord
       │                        │  14. 写入 agent1 inbox
       │                        │  (TASK_REPLY 事件)
       │                        │                        │
       │                        │  15. tick: 回复投递      │
       │                        │───────────────────────>│ (回到 agent1)
       │                        │  16. 注入回复到         │
       │                        │     agent1 的 tmux pane │
       │                        │                        │
       │  17. Agent1 看到回复    │                        │
       │<───────────────────────│                        │
       │                        │                        │
```

### 详细步骤

**Phase 1: 提交**
1. `/ask` skill 执行 `ccb ask agent2 ...`
2. `submit_ask()` (`lib/cli/services/ask_runtime/submission.py`) 解析发送方身份，连接 daemon
3. 通过 Unix socket 发送 `submit` RPC

**Phase 2: Daemon 处理**
4. `submit handler` 创建 `MessageEnvelope`
5. `dispatcher.submit()` 路由到目标 agent，创建 `JobRecord`
6. `MessageBureau` 在目标 agent 的 inbox 中追加 `TASK_REQUEST` 事件

**Phase 3: 投递执行**
7. dispatcher tick 触发 `ExecutionService.start()`
8. `claim_next()` 获取投递租约
9. provider communicator 将 prompt 注入目标 agent 的 tmux pane

**Phase 4: 完成检测**
10. provider 处理请求，输出回复 + `CCB_DONE:req_id`
11. dispatcher tick 轮询检测完成标记
12. 提取回复文本，创建 `ReplyRecord`

**Phase 5: 回复投递**
13. 在**发送方**的 inbox 中追加 `TASK_REPLY` 事件
14. 下一次 tick 触发回复投递，注入到发送方的 tmux pane
15. `ack_reply()` 标记事件 CONSUMED

---

## 7. 异步 vs 同步

| 特性 | Async (默认) | Sync (--wait) |
|------|-------------|---------------|
| 返回时机 | 提交后立即返回 | 等待回复完成后返回 |
| CLI 输出 | `[CCB_ASYNC_SUBMITTED]` | 完整回复文本 |
| 查看回复 | `ccb pend {agent}` | 直接显示 |
| 适用场景 | 多任务并行 | 需要即时结果 |

---

## 8. Job 生命周期

```
ACCEPTED → QUEUED → RUNNING → COMPLETED
                            → FAILED → (retry) → QUEUED → ...
                            → INCOMPLETE
                            → CANCELLED
```

每条 `JobRecord` 持久化在 `.ccb/agents/{agent}/jobs.jsonl`，事件跟踪在 `.ccb/agents/{agent}/events.jsonl`。

---

## 9. 关键文件索引

| 组件 | 文件路径 |
|------|----------|
| CLI 入口 | `ccb` |
| Ask 提交 | `lib/cli/services/ask_runtime/submission.py` |
| Socket 传输 | `lib/ccbd/socket_client_runtime/transport.py` |
| RPC 模型 | `lib/ccbd/api_models_runtime/rpc.py` |
| 消息信封 | `lib/ccbd/api_models_runtime/messages.py` |
| Job 记录 | `lib/ccbd/api_models_runtime/records.py` |
| Socket Server | `lib/ccbd/socket_server_runtime/server.py` |
| Handler 注册 | `lib/ccbd/handlers/__init__.py` |
| Job Dispatcher | `lib/ccbd/services/dispatcher.py` |
| 提交生命周期 | `lib/ccbd/services/dispatcher_runtime/lifecycle.py` |
| 回复投递 | `lib/ccbd/services/dispatcher_runtime/reply_delivery.py` |
| Mailbox 模型 | `lib/mailbox_kernel/models.py` |
| Mailbox 存储 | `lib/mailbox_kernel/store.py` |
| 租约机制 | `lib/mailbox_kernel/service_runtime/transitions_runtime/claiming.py` |
| 线路协议 | `lib/provider_core/protocol_runtime/constants.py` |
| Prompt 包装 | `lib/provider_core/protocol_runtime/prompt.py` |
| Claude 通信器 | `lib/provider_backends/claude/comm_runtime/communicator_facade.py` |
| Codex 通信器 | `lib/provider_backends/codex/comm_runtime/communicator_facade.py` |
| Gemini 通信器 | `lib/provider_backends/gemini/comm_runtime/communicator_facade.py` |
| Message Bureau | `lib/message_bureau/facade.py` |
| Ask skill | `claude_skills/ask/SKILL.md` |
| Pend skill | `claude_skills/pend/SKILL.md` |

---

## 10. 设计亮点与局限

### 亮点
1. **文件系统持久化** — JSONL append-only 模式，crash-safe，易于调试和审计
2. **租约机制** — 防止并发投递冲突，支持超时和孤儿恢复
3. **标记协议** — `CCB_REQ_ID`/`CCB_DONE` 实现了请求-回复关联，不需要修改 provider 本身
4. **异步优先** — 默认异步提交，避免阻塞调用方

### 局限
1. **依赖 tmux 文本注入** — 发送消息本质上是往终端里打字，provider 必须在 tmux 中运行
2. **依赖 session 日志文件** — 读取回复依赖 provider 的日志格式，升级可能破坏兼容性
3. **单点调度** — ccbd daemon 是单点，崩溃后由 keeper 重启但会丢失内存状态
4. **Droid/OpenCode 不完整** — 这两个 provider 没有完整的通信器实现
