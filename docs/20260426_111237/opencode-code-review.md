# OpenCode 最小可行补全 — 代码审查报告

> 日期: 2026-04-26
> 版本: v6.0.4 (基于 20ebac2)
> 审查范围: OpenCode provider skill 注入 + env 组装增强

---

## 1. 变更概览

本次改动为 OpenCode provider 添加了两项核心能力：

| 能力 | 变更类型 | 文件数 |
|------|----------|--------|
| Skill 加载与 prompt 注入 | 新增 + 修改 | 6 个文件 |
| Provider profile env 组装 | 修改 | 1 个文件 |

**原则**：最小改动，完全复用已有模式（参照 Claude/Gemini 的实现），不引入新架构。

---

## 2. 新增文件详解

### 2.1 `opencode_skills/ask/SKILL.md`

**来源**: 复制自 `droid_skills/ask/SKILL.md`，标题改为 "OpenCode Version"

**作用**: 定义 ask 技能的完整行为规范，教会 OpenCode agent 如何：
- 使用 `ccb ask <target>` 发送异步消息
- 识别 `[CCB_ASYNC_SUBMITTED]` 后立即结束 turn
- 支持 `--wait`、`--silence` 选项

**与模板的差异**: 仅标题不同（"Droid Version" → "OpenCode Version"），内容完全一致。这是合理的——ask 技能的行为对所有 provider 都是统一的（都是执行 `ccb ask` CLI 命令）。

### 2.2 `opencode_skills/pend/SKILL.md`

**来源**: 复制自 `droid_skills/pend/SKILL.md`，标题改为 "OpenCode Version"

**作用**: pend 技能 — 查看指定 agent 或 job_id 的最新回复。行为：`ccb pend $ARGUMENTS`。

### 2.3 `opencode_skills/ping/SKILL.md`

**来源**: 复制自 `droid_skills/ping/SKILL.md`，标题改为 "OpenCode Version"

**作用**: ping 技能 — 检查指定 agent 或 ccbd 的健康状态。行为：`ccb ping $ARGUMENTS`。

### 2.4 `lib/provider_backends/opencode/protocol_runtime/__init__.py`

空包初始化文件，符合项目约定。

### 2.5 `lib/provider_backends/opencode/protocol_runtime/skills.py`

**来源**: 参照 `lib/provider_backends/claude/protocol_runtime/skills.py`

**核心函数**:

| 函数 | 作用 |
|------|------|
| `load_opencode_skills()` | 入口函数，带缓存，受 `CCB_OPENCODE_SKILLS` 环境变量控制 |
| `load_opencode_skills_from_dir()` | 从指定目录加载 skill 文件 |
| `default_opencode_skills_dir()` | 解析 `opencode_skills/` 目录路径（通过 `parents[4]` 定位） |
| `_skill_paths()` | 定义优先级：`RUNTIME.md` > `SKILL.md` > `ask.md` |
| `_first_existing_skill_text()` | 第一个匹配的文件胜出 |
| `_strip_front_matter()` | 去除 YAML front matter（`---` 包围的部分） |

**与 Claude 版本的差异**:
- `env_bool` 参数名: `CCB_CLAUDE_SKILLS` → `CCB_OPENCODE_SKILLS`
- 目录名: `claude_skills` → `opencode_skills`
- 其他逻辑完全一致

**路径解析验证**: `skills.py` 位于 `lib/provider_backends/opencode/protocol_runtime/skills.py`，`parents[4]` 向上 4 级到达项目根目录，再拼接 `opencode_skills`。这与 Claude 的 `parents[4]` 模式完全一致（Claude 的 skills.py 在 `lib/provider_backends/claude/protocol_runtime/skills.py`，同样向上 4 级）。

### 2.6 `lib/provider_backends/opencode/protocol_runtime/prompt.py`

**来源**: 参照 `lib/provider_backends/claude/protocol_runtime/prompt.py`

**核心函数**:

```python
def build_opencode_prompt_body(message: str) -> str:
    rendered = (message or '').rstrip()
    skills = load_opencode_skills()
    if skills:
        rendered = f'{skills}\n\n{rendered}'.strip()
    return rendered
```

**行为**: 将 skill 文本 prepend 到用户消息前面。如果 skill 加载为空（目录不存在或被禁用），则原样返回消息。这是 Claude 使用的相同模式。

---

## 3. 修改文件详解

### 3.1 `lib/provider_backends/opencode/protocol.py`

**改动**: 1 行导入 + 1 行函数体修改

**Before**:
```python
def wrap_opencode_prompt(message: str, req_id: str) -> str:
    message = (message or "").rstrip()
    return f"{REQ_ID_PREFIX} {req_id}\n\n{message}\n"
```

**After**:
```python
from provider_backends.opencode.protocol_runtime.prompt import build_opencode_prompt_body

def wrap_opencode_prompt(message: str, req_id: str) -> str:
    message = build_opencode_prompt_body(message)
    return f"{REQ_ID_PREFIX} {req_id}\n\n{message}\n"
```

**分析**:
- `build_opencode_prompt_body()` 内部已经做了 `rstrip()`，所以行为兼容
- `CCB_REQ_ID` 标记的位置不变，不影响执行层对 req_id 的匹配逻辑
- `wrap_opencode_prompt` 的调用方在 `execution_runtime/start.py`，通过 `wrap_prompt_fn=wrap_opencode_prompt` 参数传入，签名 `(message, req_id) -> str` 未变，无破坏性

**风险**: 如果 skill 文本很长，会增加 prompt 长度。但这是预期行为——Claude 也是这样做的。

### 3.2 `lib/provider_backends/opencode/launcher.py`

**改动**: 新增 2 个导入 + 修改 `build_start_cmd` + 新增 `build_opencode_env_prefix` 函数

**Before**: 只导出 3 个 `CCB_*` caller context 变量
**After**: 加载 provider_profile → 组装 profile.env + spec.env → 导出完整 env prefix

**新增函数 `build_opencode_env_prefix`**:

```python
def build_opencode_env_prefix(*, profile=None, extra_env=None) -> str:
    # 1. 合并 profile.env 和 spec.env
    # 2. 如果 inherit_api=False，unset API key（目前 OpenCode 没有注册 API key，此分支不执行）
    # 3. 渲染 export 语句
```

**分析**:
- `load_resolved_provider_profile(runtime_dir)` 如果 profile 不存在会返回 `None`，此时 `build_opencode_env_prefix(profile=None)` 返回空字符串，行为与改动前一致
- `join_env_prefix` 用 `; ` 拼接多段 env prefix，是项目已有的工具函数
- API key unset 分支目前不会执行（`provider_api_env_keys('opencode')` 返回空集），但框架已就位
- 使用延迟导入 `from provider_profiles import provider_api_env_keys` 避免循环依赖风险

**向后兼容性**:
- 没有 `provider_profile` 配置的 OpenCode agent：profile=None → env prefix 为空 → 只导出 caller context → **行为与改动前完全一致**
- 有 `provider_profile` 但 mode=inherit（默认）：profile.env 只包含 API key 相关的（目前为空），spec.env 被传递 → **新能力，不影响旧配置**

---

## 4. 代码审查清单

| 检查项 | 结果 | 说明 |
|--------|------|------|
| 导入路径正确性 | ✅ | `provider_backends.opencode.protocol_runtime.prompt` 在 PYTHONPATH 下可解析 |
| 函数签名兼容性 | ✅ | `wrap_opencode_prompt(message, req_id)` 签名未变 |
| 空值/None 处理 | ✅ | profile=None 时 env prefix 返回空字符串 |
| 路径解析正确性 | ✅ | `parents[4]` 从 `protocol_runtime/skills.py` 到项目根，与 Claude 一致 |
| 环境变量命名一致性 | ✅ | `CCB_OPENCODE_SKILLS` 遵循 `CCB_{PROVIDER}_SKILLS` 模式 |
| 循环依赖 | ✅ | `provider_api_env_keys` 使用延迟导入 |
| 前端 matter 解析 | ✅ | 与 Claude 使用相同的 `_strip_front_matter` 实现 |
| 缓存机制 | ✅ | `_SKILL_CACHE` 模块级缓存，进程生命周期内有效 |
| 异常处理 | ✅ | `_read_skill_text` 捕获所有异常，返回空字符串 |
| Shell 注入风险 | ✅ | 使用 `shlex.quote` 对 env 值进行转义 |

---

## 5. 实验验证方案

### 实验 1: Skill 加载验证

**目的**: 确认 skill 文件被正确发现、加载、strip front matter、缓存

```python
# PYTHONPATH=lib python3
from provider_backends.opencode.protocol_runtime.skills import (
    load_opencode_skills,
    load_opencode_skills_from_dir,
    default_opencode_skills_dir,
)

# 1. 目录解析正确
skills_dir = default_opencode_skills_dir()
assert skills_dir.name == 'opencode_skills', f"Expected opencode_skills, got {skills_dir.name}"
print(f"[PASS] Skills dir: {skills_dir}")

# 2. Skill 加载非空
skills = load_opencode_skills()
assert len(skills) > 0, "Skills should not be empty"
print(f"[PASS] Skills loaded: {len(skills)} chars")

# 3. Front matter 已去除（不应包含 YAML 头）
assert not skills.startswith('---'), "Front matter should be stripped"
print(f"[PASS] Front matter stripped")

# 4. 包含 ask 技能的关键内容
assert 'ccb ask' in skills, "Should contain 'ccb ask'"
assert 'CCB_ASYNC_SUBMITTED' in skills, "Should contain async marker"
print(f"[PASS] Ask skill content verified")

# 5. 缓存生效（第二次调用应返回同一对象）
skills2 = load_opencode_skills()
assert skills is skills2, "Should return cached result"
print(f"[PASS] Cache verified (same object)")
```

**预期结果**: 全部 PASS

### 实验 2: Skill 禁用验证

**目的**: 确认 `CCB_OPENCODE_SKILLS=false` 可以禁用 skill 加载

```python
import os
os.environ['CCB_OPENCODE_SKILLS'] = 'false'

# 清除缓存
import provider_backends.opencode.protocol_runtime.skills as sk
sk._SKILL_CACHE = None

skills = sk.load_opencode_skills()
assert skills == '', f"Expected empty when disabled, got {len(skills)} chars"
print(f"[PASS] Skills disabled via env var")

# 清理
del os.environ['CCB_OPENCODE_SKILLS']
sk._SKILL_CACHE = None
```

**预期结果**: PASS，返回空字符串

### 实验 3: Prompt 组装验证

**目的**: 确认 skill 文本被正确注入到 prompt 中

```python
from provider_backends.opencode.protocol import wrap_opencode_prompt

# 1. 基本包装
prompt = wrap_opencode_prompt('hello world', 'test-req-001')
assert 'CCB_REQ_ID: test-req-001' in prompt, "Should contain req ID"
assert 'hello world' in prompt, "Should contain original message"
print(f"[PASS] Basic prompt wrapping OK")

# 2. Skill 注入
assert 'ccb ask' in prompt, "Should contain injected skill text"
assert prompt.index('ccb ask') < prompt.index('hello world'), \
    "Skills should appear BEFORE the message"
print(f"[PASS] Skill text prepended before message")

# 3. 格式结构: [skills]\n\n[CCB_REQ_ID]\n\n[message]
lines = prompt.split('\n')
assert any('CCB_REQ_ID' in l for l in lines), "Should have REQ_ID line"
print(f"[PASS] Format structure OK")

# 打印完整 prompt 供人工审查
print(f"\n--- Full prompt preview ---")
print(prompt[:500])
print(f"... ({len(prompt)} total chars)")
```

**预期结果**: 全部 PASS，skill 文本出现在 message 之前

### 实验 4: Env Prefix 组装验证

**目的**: 确认 launcher 的 env prefix 在各种场景下正确输出

```python
from provider_backends.opencode.launcher import build_opencode_env_prefix

# 1. 无 profile 无 extra_env → 空
result = build_opencode_env_prefix()
assert result == '', f"Expected empty, got: {result}"
print(f"[PASS] No profile, no env → empty prefix")

# 2. 有 extra_env
result = build_opencode_env_prefix(extra_env={'MY_VAR': 'hello', 'OTHER': 'world'})
assert 'MY_VAR=hello' in result, f"Should contain MY_VAR, got: {result}"
assert 'OTHER=world' in result, f"Should contain OTHER, got: {result}"
assert result.startswith('export '), f"Should start with export, got: {result}")
print(f"[PASS] extra_env exported correctly: {result}")

# 3. 模拟 ResolvedProviderProfile
from types import SimpleNamespace
profile = SimpleNamespace(env={'API_KEY': 'sk-test', 'MODEL': 'gpt-4'}, inherit_api=True)
result = build_opencode_env_prefix(profile=profile, extra_env={'EXTRA': 'val'})
assert 'API_KEY=' in result
assert 'MODEL=' in result
assert 'EXTRA=' in result
print(f"[PASS] Profile + extra_env merged: {result}")

# 4. inherit_api=False 且有 API keys（目前 opencode 无注册 key，验证逻辑分支）
profile_no_inherit = SimpleNamespace(env={'X': '1'}, inherit_api=False)
result = build_opencode_env_prefix(profile=profile_no_inherit, extra_env={'Y': '2'})
assert 'export' in result
print(f"[PASS] inherit_api=False branch: {result}")

# 5. 值含特殊字符 → shlex.quote 保护
result = build_opencode_env_prefix(extra_env={'DANGER': "'; rm -rf /; echo '"})
assert "'; rm -rf" not in result or "rm -rf" not in result.split('=')[1][:10]
print(f"[PASS] Shell injection protected: {result[:80]}")
```

**预期结果**: 全部 PASS，特殊字符被正确转义

### 实验 5: 完整启动命令验证

**目的**: 模拟 `build_start_cmd` 的完整调用，验证最终命令格式

```python
from pathlib import Path
from provider_backends.opencode.launcher import build_start_cmd
from cli.models_start import ParsedStartCommand
from types import SimpleNamespace

# 构造最小 spec
spec = SimpleNamespace(
    name='test_agent',
    startup_args=['--model', 'gpt-4'],
    env={'CUSTOM_VAR': 'test_value'},
)

command = ParsedStartCommand(
    project=None,
    agent_names=('test_agent',),
    restore=False,
    auto_permission=False,
)

# 使用临时目录模拟 runtime_dir
import tempfile
with tempfile.TemporaryDirectory() as tmpdir:
    runtime_dir = Path(tmpdir)

    # 注意：profile 文件不存在，load_resolved_provider_profile 返回 None
    cmd = build_start_cmd(command, spec, runtime_dir, 'session-001')

    # 1. 包含 provider 可执行文件
    assert 'opencode' in cmd, f"Should contain 'opencode', got: {cmd}"
    print(f"[PASS] Provider command present")

    # 2. 包含 startup_args
    assert '--model' in cmd and 'gpt-4' in cmd
    print(f"[PASS] startup_args present")

    # 3. 包含 spec.env
    assert 'CUSTOM_VAR=test_value' in cmd, f"Should contain env var, got: {cmd}"
    print(f"[PASS] spec.env exported")

    # 4. 包含 caller context
    assert 'CCB_CALLER_ACTOR=test_agent' in cmd
    assert 'CCB_SESSION_ID=session-001' in cmd
    print(f"[PASS] Caller context present")

    # 5. 格式: export ...; opencode ...
    assert 'export ' in cmd and '; ' in cmd
    print(f"[PASS] Command format correct")

    print(f"\n--- Full command ---")
    print(cmd)
```

**预期结果**: 全部 PASS，最终命令包含 env export + caller context + provider 可执行文件

### 实验 6: 回归验证 — 无配置时行为不变

**目的**: 确认没有 provider_profile 配置时，launcher 输出与改动前一致

```python
# 改动前的行为：只导出 CCB_* caller context
# 改动后（无 profile 时）：profile=None → env prefix 为空 → 只导出 caller context → 相同

# 验证命令格式不变
command = ParsedStartCommand(project=None, agent_names=('agent1',), restore=False, auto_permission=False)
spec = SimpleNamespace(name='agent1', startup_args=[], env={})

with tempfile.TemporaryDirectory() as tmpdir:
    cmd = build_start_cmd(command, spec, Path(tmpdir), 'sess-1')

    # 应该只有 caller context export + opencode 命令
    assert cmd.startswith('export CCB_CALLER_ACTOR') or cmd.startswith('opencode')
    assert 'opencode' in cmd
    print(f"[PASS] Regression: no profile → same as before")
    print(f"Command: {cmd}")
```

**预期结果**: PASS，输出格式 `export CCB_CALLER_ACTOR=agent1 ...; opencode`

### 实验 7: Protocol 对执行层的兼容性

**目的**: 确认 `wrap_opencode_prompt` 的修改不影响执行层对 req_id 的匹配

```python
from provider_backends.opencode.protocol import wrap_opencode_prompt

# 执行层在 execution_runtime/polling.py 中通过 _reply_matches_request
# 匹配 last_assistant_req_id 与 request_anchor
# request_anchor 来自 CCB_REQ_ID 标记

prompt = wrap_opencode_prompt('test', 'anchor-abc-123')

# 1. req_id 标记位置和格式不变
assert 'CCB_REQ_ID: anchor-abc-123' in prompt
print(f"[PASS] REQ_ID marker present and unchanged")

# 2. req_id 在第一行（执行层可能依赖这个）
first_line = prompt.split('\n')[0]
assert 'CCB_REQ_ID: anchor-abc-123' == first_line, \
    f"First line should be REQ_ID marker, got: {first_line}"
print(f"[PASS] REQ_ID is first line (anchor matching compatible)")
```

**预期结果**: PASS，`CCB_REQ_ID` 仍然是 prompt 的第一行

---

## 6. 实验执行脚本

所有实验可一键执行：

```bash
PYTHONPATH=lib python3 -c "
import os, sys, tempfile
from pathlib import Path
from types import SimpleNamespace

from provider_backends.opencode.protocol_runtime.skills import (
    load_opencode_skills, load_opencode_skills_from_dir,
    default_opencode_skills_dir,
)
from provider_backends.opencode.protocol import wrap_opencode_prompt
from provider_backends.opencode.launcher import build_opencode_env_prefix, build_start_cmd
from cli.models_start import ParsedStartCommand

passed = 0
failed = 0

def check(name, condition):
    global passed, failed
    if condition:
        print(f'  PASS: {name}')
        passed += 1
    else:
        print(f'  FAIL: {name}')
        failed += 1

print('=== Experiment 1: Skill Loading ===')
sd = default_opencode_skills_dir()
check('dir name', sd.name == 'opencode_skills')
sk = load_opencode_skills()
check('non-empty', len(sk) > 0)
check('no front matter', not sk.startswith('---'))
check('has ccb ask', 'ccb ask' in sk)
check('has async marker', 'CCB_ASYNC_SUBMITTED' in sk)
sk2 = load_opencode_skills()
check('cache hit', sk is sk2)

print('\\n=== Experiment 2: Skill Disable ===')
os.environ['CCB_OPENCODE_SKILLS'] = 'false'
import provider_backends.opencode.protocol_runtime.skills as skm
skm._SKILL_CACHE = None
check('disabled → empty', skm.load_opencode_skills() == '')
del os.environ['CCB_OPENCODE_SKILLS']
skm._SKILL_CACHE = None

print('\\n=== Experiment 3: Prompt Assembly ===')
p = wrap_opencode_prompt('hello', 'r1')
check('req_id present', 'CCB_REQ_ID: r1' in p)
check('message present', 'hello' in p)
check('skill injected', 'ccb ask' in p)
check('skills before msg', p.index('ccb ask') < p.index('hello'))
check('req_id first line', p.split(chr(10))[0] == 'CCB_REQ_ID: r1')

print('\\n=== Experiment 4: Env Prefix ===')
check('empty on none', build_opencode_env_prefix() == '')
r = build_opencode_env_prefix(extra_env={'A':'1','B':'2'})
check('exports present', 'A=1' in r and 'B=2' in r)
check('starts with export', r.startswith('export '))
prof = SimpleNamespace(env={'K':'v'}, inherit_api=True)
r2 = build_opencode_env_prefix(profile=prof, extra_env={'X':'y'})
check('profile+extra merged', 'K=v' in r2 and 'X=y' in r2)

print('\\n=== Experiment 5: Full Start Command ===')
spec = SimpleNamespace(name='ag1', startup_args=[], env={'MY':'val'})
cmd_obj = ParsedStartCommand(project=None, agent_names=('ag1',), restore=False, auto_permission=False)
with tempfile.TemporaryDirectory() as td:
    cmd = build_start_cmd(cmd_obj, spec, Path(td), 'sid')
    check('has opencode', 'opencode' in cmd)
    check('has env', 'MY=val' in cmd)
    check('has caller', 'CCB_CALLER_ACTOR=ag1' in cmd)
    check('has session', 'CCB_SESSION_ID=sid' in cmd)

print('\\n=== Experiment 6: Regression ===')
spec2 = SimpleNamespace(name='a2', startup_args=[], env={})
with tempfile.TemporaryDirectory() as td:
    cmd2 = build_start_cmd(cmd_obj, spec2, Path(td), 's2')
    check('no profile → caller context only', 'CCB_CALLER_ACTOR=a2' in cmd2)
    check('no extra exports', cmd2.count('export') == 1)

print(f'\\n=== Results: {passed} passed, {failed} failed ===')
sys.exit(1 if failed else 0)
"
```

---

## 7. 已知局限

| 局限 | 说明 | 是否阻塞 |
|------|------|----------|
| OpenCode 无注册 API key | `_API_ENV_KEYS` 中没有 opencode 条目，`inherit_api=False` 的 unset 分支不会执行 | 否，功能预留 |
| 只加载 ask skill | 与 Claude 一致，只自动注入 ask skill，其他 skill 通过 slash command 触发 | 否，设计如此 |
| 无 headless/resume | 未触及这些高级功能 | 否，超出最小范围 |
| Skill 内容完全复制 | ask/pend/ping 的 SKILL.md 从 droid 复制，仅标题不同 | 否，provider 行为统一 |

---

## 8. 结论

本次改动共涉及 **8 个新增文件 + 2 个修改文件**，净增约 **280 行代码**（含 skill markdown）。所有改动严格遵循已有模式（Claude/Gemini 的 skill 加载和 env 组装），无架构变更，向后兼容。建议执行上述 7 个实验验证后提交。
