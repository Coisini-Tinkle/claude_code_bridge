# 实验日志：CCB v6.0.4 vs v6.0.12 环境变量继承对比

**日期**：2026-04-25  
**实验类型**：回归分析 / 静态验证  
**相关代码**：`lib/ccbd/daemon_process.py`、`lib/runtime_env/control_plane.py`  
**问题来源**：用户报告 v6.0.12 代理不生效

---

## 1. 背景与问题

用户报告 CCB 从 v6.0.4 升级到 v6.0.12 后，代理环境变量（`HTTP_PROXY`、`HTTPS_PROXY` 等）不再生效，导致网络请求无法通过代理。

v6.0.4 在同一环境下代理正常工作，v6.0.12 失效。

## 2. 实验目标与假设

**目标**：验证 v6.0.4 和 v6.0.12 在环境变量继承上的差异，确认代理失效的根本原因。

**假设**：
1. v6.0.12 引入了环境变量白名单过滤机制
2. 代理环境变量不在白名单中，被过滤掉
3. 这导致 provider 进程无法获取代理配置

## 3. 实验设置

| 项目 | 配置 |
|---|---|
| 入口命令 | Python 脚本模拟对比 |
| 基线 | v6.0.4 行为：`env = dict(os.environ)` |
| 变量 | v6.0.12 行为：`env = control_plane_env()` |
| 固定条件 | 相同测试环境变量集合 |
| 评估指标 | 环境变量是否被继承 |

### 3.1 关键代码变更

**v6.0.4 (`lib/ccbd/daemon_process.py`)**:

```python
def _ccbd_env(*, keeper_pid: int | None) -> dict[str, str]:
    env = dict(os.environ)  # 直接继承所有环境变量
    env['PYTHONUNBUFFERED'] = '1'
    # ...
    return env
```

**v6.0.12 (`lib/ccbd/daemon_process.py`)**:

```python
def _ccbd_env(*, keeper_pid: int | None) -> dict[str, str]:
    env = control_plane_env(extra={'PYTHONUNBUFFERED': '1'})  # 使用白名单过滤
    # ...
    return env
```

**v6.0.12 新增 (`lib/runtime_env/control_plane.py`)**:

```python
_CONTROL_PLANE_ALLOWLIST = {
    'ANTHROPIC_API_KEY',
    'PATH',
    'HOME',
    # ... 注意：没有 HTTP_PROXY、HTTPS_PROXY 等
}

def control_plane_env(*, extra=None):
    env = {}
    for key, value in os.environ.items():
        if key in _CONTROL_PLANE_BLOCKED_EXACT:
            continue
        if key in _CONTROL_PLANE_ALLOWLIST:
            env[key] = value
            continue
        if any(key.startswith(prefix) for prefix in _CONTROL_PLANE_BLOCKED_PREFIXES):
            continue
        if key.startswith(('PYTHON', 'VIRTUAL_ENV', 'CONDA')):
            env[key] = value
        # 其他变量全部丢弃！
    return env
```

## 4. 对照设计

| 方案 | 改动 | 目的 | 预期 |
|---|---|---|---|
| v6.0.4 | `dict(os.environ)` | 基线参照 | 继承所有环境变量 |
| v6.0.12 | `control_plane_env()` | 白名单过滤 | 只继承白名单变量 |

## 5. 结果汇总

| 环境变量 | v6.0.4 | v6.0.12 | 结论 |
|---|:---:|:---:|---|
| HTTP_PROXY | ✓ 继承 | ✗ 过滤 | 代理失效 |
| HTTPS_PROXY | ✓ 继承 | ✗ 过滤 | 代理失效 |
| ALL_PROXY | ✓ 继承 | ✗ 过滤 | 代理失效 |
| http_proxy | ✓ 继承 | ✗ 过滤 | 代理失效 |
| https_proxy | ✓ 继承 | ✗ 过滤 | 代理失效 |
| PUSHOVER_TOKEN | ✓ 继承 | ✗ 过滤 | 自定义变量丢失 |
| PUSHOVER_USER_KEY | ✓ 继承 | ✗ 过滤 | 自定义变量丢失 |
| MY_CUSTOM_VAR | ✓ 继承 | ✗ 过滤 | 自定义变量丢失 |

## 6. 现象观察

- v6.0.4 使用 `dict(os.environ)` 直接复制所有环境变量
- v6.0.12 使用 `control_plane_env()` 函数进行白名单过滤
- 白名单 `_CONTROL_PLANE_ALLOWLIST` 不包含任何代理相关变量
- 白名单逻辑只额外保留 `PYTHON`、`VIRTUAL_ENV`、`CONDA` 开头的变量
- 代理变量和用户自定义变量全部被过滤

## 7. 分析与解释

**事实**：
- v6.0.5+ 引入 `control_plane_env()` 函数（提交记录未明确标注，但在版本演进中出现）
- 该函数使用显式白名单过滤环境变量
- 代理环境变量（HTTP_PROXY、HTTPS_PROXY、ALL_PROXY）不在白名单中

**推断**：
- 设计者可能考虑安全性，限制传递给控制平面的环境变量
- 但忽略了代理配置的常见需求
- 这是一个**回归问题**，影响依赖代理的网络环境

**根本原因确认**：

```python
# 白名单不包含代理变量
_CONTROL_PLANE_ALLOWLIST = {
    'ANTHROPIC_API_KEY',
    'PATH',
    'HOME',
    # ... 没有 HTTP_PROXY, HTTPS_PROXY, ALL_PROXY, NO_PROXY
}

# 过滤逻辑丢弃所有非白名单变量
if key.startswith(('PYTHON', 'VIRTUAL_ENV', 'CONDA')):
    env[key] = value
# 代理变量不满足任何保留条件，被丢弃
```

## 8. 可行性验证

| 方案 | 验证方式 | 命令/检查方法 | 状态 |
|---|---|---|---|
| 使用 launch_env 配置 | 静态验证 | 查看 `ccb` 脚本 `launch_env` 实现 | 支持继续 |
| 修改白名单添加代理变量 | 静态验证 | 检查 `control_plane.py` 可编辑性 | 支持继续 |

### 8.1 解决方案一：使用 launch_env 配置

v6.0.5+ 支持 `.ccb/ccb.config` 中的 `launch_env` 配置：

```json
{
  "cmd": "agent1:codex",
  "launch_env": {
    "codex": {
      "HTTP_PROXY": "http://127.0.0.1:7890",
      "HTTPS_PROXY": "http://127.0.0.1:7890"
    }
  }
}
```

**优点**：无需修改代码，配置即可生效  
**缺点**：需要手动配置，不够自动

### 8.2 解决方案二：修改白名单

在 `lib/runtime_env/control_plane.py` 中添加：

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

**优点**：一劳永逸，所有用户受益  
**缺点**：需要提交 PR 到上游

## 9. 结论

**假设验证结果**：
1. ✓ 确认 v6.0.12 引入了环境变量白名单过滤机制
2. ✓ 确认代理环境变量不在白名单中被过滤
3. ✓ 确认这是导致代理失效的根本原因

**结论**：
v6.0.5+ 引入的 `control_plane_env()` 函数使用白名单过滤环境变量，代理相关变量不在白名单中，导致代理配置无法传递给 provider 进程。这是一个设计上的疏忽，影响所有依赖代理的用户。

## 10. 后续计划

1. **短期**：在 `.ccb/ccb.config` 中配置 `launch_env` 解决当前问题
2. **中期**：向 CCB 上游提交 Issue 或 PR，建议在白名单中添加代理变量
3. **长期**：考虑是否需要更灵活的环境变量继承机制（如 `CCB_INHERIT_ENV` 配置）

## 11. 可复现信息

- Git 状态：v6.0.4 vs v6.0.12 对比
- 关键文件：
  - `lib/ccbd/daemon_process.py` - 环境变量入口
  - `lib/runtime_env/control_plane.py` - 白名单定义（v6.0.12 新增）
- 验证命令：
  ```bash
  git show v6.0.4:lib/ccbd/daemon_process.py | grep -A10 "def _ccbd_env"
  git show v6.0.12:lib/ccbd/daemon_process.py | grep -A10 "def _ccbd_env"
  git show v6.0.12:lib/runtime_env/control_plane.py
  ```
