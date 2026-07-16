# 架构债与待改造清单

本文件记录已经确认、但暂不在当前学习阶段修改的运行时问题。每一项在改造前都应补充针对性的回归测试，并复核相关 provider / transport 行为。

> 校正约定：本清单最初来自旧版源码。学习最新版时，已经由代码确认修复的条目会保留历史问题描述，并标记为“已修改（待回归验证）”；只有通过针对性测试后才可标为“已验证”。当前校正基线：`main` 的 `7b1afd0`。

## 优先级总览（2026-07-15）

以下排序按“可被远程输入或模型触发的安全突破”优先，其次是敏感数据泄露/跨用户串话、数据不可恢复损坏、核心对话正确性，最后才是可用性、可观测性与维护成本。`P0` 是发布前必须关闭或显式降级的风险；`P1` 应进入紧随其后的迭代；`P2` 纳入常规工程计划；`P3` 是体验或维护性优化。正文仍保留原 AD 编号，便于追溯学习记录。

| 顺序 | 优先级 | 条目 | 排序理由 |
|---:|:---:|---|---|
| 1 | P0 | AD-038 | `execute_code` 是没有真实 OS 隔离的任意代码执行入口，且当前文案会造成错误安全预期。 |
| 2 | P0 | AD-044 | 已修改（待回归验证）：统一 persistence sanitizer；既有库扫描/加密证据仓仍待补。 |
| 3 | P0 | AD-006 | 外部工具输出跨 Turn 被重放为用户消息，破坏提示注入防线和审计信任边界。 |
| 4 | P0 | AD-009 | 已验证：桥接继承执行上下文；配额/审计与 ask-first network 授权回归已通过。 |
| 5 | P0 | AD-014 | 已验证：`memory_ingest` 已移除；共享 `file_access` 锁定敏感路径旁路。 |
| 6 | P0 | AD-027 | 已验证：命名会话 key 含 `chat_id`，同名跨群聊不再共享上下文。 |
| 7 | P0（回归门） | AD-015 | 外部记忆的 scope 隔离虽已改进，必须先用多用户回归测试证明不会召回他人数据。 |
| 8 | P1 | AD-001 | 上下文溢出会导致核心对话请求失败，且缺少可恢复、可解释的闭环。 |
| 9 | P1 | AD-005 | 会话、压缩链与观测数据跨存储非原子，崩溃时可能产生不可恢复的不一致。 |
| 10 | P1 | AD-008 | 进程级取消状态会让一个 session 的 `/stop` 影响另一个 session。 |
| 11 | P1 | AD-010 | 文件读写可造成内存压力、策略绕过与半写入损坏。 |
| 12 | P1 | AD-036 | 前台命令与代码执行会在截断前无界缓存输出，存在资源耗尽风险。 |
| 13 | P1 | AD-037 | Windows 子进程可能在超时或停止后残留，`execute_code` 也无法及时响应停止。 |
| 14 | P1 | AD-039 | `bwrap` 仅隔离写入却被表述为文件系统隔离，Linux 部署会误判机密读取能力。 |
| 15 | P1 | AD-047 | 流式响应开始后仍重试会重复输出、拼坏工具参数并额外计费。 |
| 16 | P1 | AD-046 | 合法零参数工具会被错误拒绝，且参数错误缺少明确语义。 |
| 17 | P1（先复现） | RI-001 | 同一 session 并发 Turn 可能破坏历史顺序和 Agent 状态，应先用压测确认。 |
| 18 | P1 | AD-003 | JSON 索引与 SQLite 活跃状态漂移，可误排序或误清理活跃会话。 |
| 19 | P1 | AD-004 | 压缩会话重命名后 lineage 的查询、审计和诊断会不完整。 |
| 20 | P1 | AD-007 | 压缩摘要冒充用户消息，会污染审计并放大错误摘要。 |
| 21 | P1 | AD-022 | Workflow 的全局运行上下文在并发执行时会串话。 |
| 22 | P1 | AD-030 | LRU 可淘汰仍被占用的平台聊天锁，破坏并发互斥。 |
| 23 | P1 | AD-031 | 同步 Hook 绕过超时控制，可阻塞整个事件循环。 |
| 24 | P1 | AD-032 | 多图输入没有回合级成本/载荷上限，容易绕过上下文预算。 |
| 25 | P1 | AD-033 | 原生图片输入不随会话持久化，后续 Turn 无法可靠重放语义。 |
| 26 | P2 | AD-035 | 显式 Skill 全文只注入本 Turn 第一次调用，后续工具循环可能失去约束。 |
| 27 | P2 | AD-040 | 工具发现后的 schema 与模型实际可调用工具不一致，跨 Provider 可靠性差。 |
| 28 | P2 | AD-043 | Tool Run 与 Turn Report 分开提交，崩溃后可观测性出现空洞。 |
| 29 | P2 | AD-042 | `ToolRegistry.dispatch()` 是潜在的 Executor 绕过旁路；当前未被生产路径调用。 |
| 30 | P2 | AD-041 | 审计日志同步写入且静默失败，不能作为可靠审计证据。 |
| 31 | P2 | AD-029 | 事件协议只在测试校验，运行时无法阻止不完整事件。 |
| 32 | P2 | AD-045 | 缺少 CI、静态检查和覆盖率门禁，无法持续防止上述边界回归。 |
| 33 | P2（回归门） | AD-011 | 文件记忆的 session/profile 全局状态已改进，需用并发隔离测试完成验收。 |
| 34 | P2（回归门） | AD-012 | Memory Review 已受限，仍需证明它不能重新获得主 Agent 工具能力。 |
| 35 | P2（回归门） | AD-013 | 记忆快照刷新已改进，需验证写入在下一 Turn 可见且不会跨 profile 泄露。 |
| 36 | P2 | AD-019 | 受限子 Agent 的研究工具与网络隔离策略互相矛盾。 |
| 37 | P2 | AD-020 | 子 Agent 超时不是整个 Run 的截止时间，成本与等待时间不可控。 |
| 38 | P2 | AD-021 | 子 Agent 的结构化输出只做浅层校验。 |
| 39 | P2 | AD-023 | Review Workflow 缺少证据获取闭环，结论可信度不足。 |
| 40 | P2 | AD-024 | Review 的验证扇出和成本缺少上限。 |
| 41 | P2 | AD-025 | 配置快照混淆 `.env` 与进程环境来源，诊断和审计不准确。 |
| 42 | P2 | AD-026 | Gateway 动态会话切换路由不持久化，重启后行为不一致。 |
| 43 | P3 | AD-002 | 空最终回复已经修复；额外 LLM 总结属于体验增强。 |
| 44 | P3 | AD-018 | RequestPlan 缓存分层尚未成为真实 Provider 缓存边界。 |
| 45 | P3 | AD-028 | Slash Command 元数据与分发逻辑双维护，主要增加维护成本。 |
| 46 | P3 | AD-034 | Skill `triggers` 尚未接入命令解析，属于功能完整性问题。 |

### 前三项修改计划

#### 1. AD-038：先关闭伪沙箱的任意代码执行入口

**目标：** 在没有真实隔离能力时，绝不把 `execute_code` 表述或实现为安全沙箱；在具备真实隔离能力时，把它收敛为一个最小权限的代码运行模块。

1. **立即止血（一个小版本）**：删除“sandboxed / 无法访问 agent files”的描述；将 `execute_code` 标为高风险、不可并行、必须显式确认，并在 `read-only`、`ask-first` 等默认安全 profile 中禁用。隔离 Adapter 不可用时 fail-closed，不退化为当前用户权限下的 Python 子进程。
2. **建立执行 seam（一个中版本）**：抽出 `CodeRunner` interface，由 Windows 与 Linux Adapter 分别实现。Adapter 必须返回实际能力快照：可读挂载、可写输出、网络、CPU/内存/进程数、超时和取消能力；`ToolEntry` 只依赖这一快照，不能声称超过 Adapter 实际提供的保证。
3. **真实隔离与资源契约（一个大版本）**：使用受限账户/容器/平台 sandbox（Windows 可结合 Job Object，Linux 可用最小 bwrap 根文件系统）；默认无网络，只暴露只读输入和受控输出目录。路径与网络访问用 `ResourceRequirement` 显式建模，超时、`/stop`、异常统一终止整棵进程树。
4. **验收测试**：默认 profile 下绝对路径读取、网络连接、派生进程全部失败；隔离 Adapter 缺失时工具不可执行；允许目录的读写、输出收集、超时、`/stop` 和 Windows 子进程回收均可重复验证。该计划会顺带关闭 AD-036、AD-037 的执行层部分风险。

#### 2. AD-044：在所有持久化出口建立统一脱敏策略

**目标：** `state.db`、JSONL 审计、导出与 CLI 展示都只保存/展示经过同一策略处理的安全投影；完整原始工具输出不再默认持久化。

1. **定义数据分类**：新增唯一的 persistence sanitizer module，区分 `public`、`sensitive`、`secret`、`debug-opt-in`；递归处理文本、URL query、嵌套 metadata 与 artifact。将现有 `clean_text()` 的编码清理职责与 `redact()` 的秘密识别职责合并为明确且可测试的接口。
2. **收敛写入 seam**：`save_tool_runs()`、`save_turn_report()`、会话导出与 audit writer 一律调用该 sanitizer；`full_output` 默认改为“长度受限、脱敏摘要”，artifact metadata 改为 allowlist。禁止业务调用绕过该 module 直接写 JSON/SQLite。
3. **处理原始证据的例外**：如确有调试需求，单独设计显式 opt-in 的加密证据仓，采用受限文件权限、密钥管理、保留期限和访问审计；不要把原文继续塞进 `state.db`。升级时提供一次性扫描/告警或迁移工具，提示既有数据库可能含敏感内容。
4. **验收测试**：输入 API key、Bearer token、Cookie、URL query secret、嵌套 dict/list 与异常栈后，检查 SQLite、audit、export、`/tool-runs show` 均不含明文；普通诊断字段仍可查询；长度截断和关联键保持正确。

#### 3. AD-006：以保留来源的会话事件模型替代“扁平 user 文本”重放

**目标：** 工具结果、压缩摘要与用户输入在持久化、重放、导出和模型消息组装中保持可区分的来源与信任级别。

1. **建立 canonical conversation event**：为 `user_input`、`assistant_text`、`tool_call`、`tool_result`、`system_summary` 定义稳定事件类型，至少保存 `origin`、`tool_name`、`tool_use_id`、`trust_level`、时间和 source range。`role="user"` 不再承担工具结果或摘要的存储语义。
2. **将 Provider 转换收敛到 Adapter**：持久层只读写 canonical event；Anthropic 等支持原生工具历史的 Adapter 还原原生 block。对不支持的 Provider，转换为带不可执行说明的受控 tool-result 包装，且在系统指令中明确它不是用户命令。
3. **兼容迁移与审计**：旧数据库没有足够 provenance 时，按保守策略标成 `legacy_untrusted`，不可重新标为用户输入；导出、压缩和 Turn Report 显示来源。与 AD-007 共用该模型，避免摘要再次冒充用户。
4. **验收测试**：恶意网页、文件和命令输出在下一 Turn 不能改变授权或触发其中的指令；跨 Provider 重放满足消息顺序协议；导出能精确区分用户、工具和系统摘要；旧记录迁移不会静默提升信任级别。

### 推荐实施顺序与门禁

先完成 AD-038 的立即止血，再完成 AD-044 的写入出口收敛，随后落地 AD-006 的 canonical event。三项都应以“先写失败回归测试、再修改实现、最后接入 CI（AD-045）”推进。AD-009 与 AD-014 作为同一安全发布批次的阻断项：前三项任一完成后，不应把它们降级为普通功能迭代。

## AD-001：上下文超限缺少硬性预算门与恢复闭环

**状态：** 已确认，待改造。

**相关代码：**

- `src/personal_agent/agent/context.py`：Turn 开始时的上下文压缩。
- `src/personal_agent/compression/simple.py`：旧工具结果清理与摘要压缩。
- `src/personal_agent/agent/loop.py`：每次 LLM 请求前构建消息、请求模型、处理异常。

### 当前行为

1. `build_turn_context()` 在一个用户 Turn 开始时，根据压缩阈值压缩历史消息。
2. 简单压缩器会优先清理早期工具结果，再尝试使用 LLM 摘要中间历史，保留头部和尾部消息。
3. `run_conversation()` 在每次调用 LLM 前计算上下文用量并上报事件，但该预算只用于观测，并不阻止超限请求。

### 新版核验（`main` @ `7b1afd0`）

- `context_budget.py` 已把 System Prompt、历史消息、普通工具/MCP Schema、Skill 与 Memory 分项估算，并将 `remaining_context` 限制为不小于零；`loop.py` 会把这个结果写入 `llm_start` / `llm_end` 事件与 Turn Report。这是**可观测性增强**，不是准入控制。
- `build_turn_context()` 只在一个 Turn 开始时执行 `_check_and_compress()`。它把 Skill、Memory 等临时注入纳入压缩阈值判断，压缩器也新增了“先移除早期 tool_result、再摘要”的两步策略和失败降级截断。
- 但 `run_conversation()` 在每一次 LLM 调用前只调用 `_build_request_context_budget()`，随后仍无条件执行 `transport.call(...)`；没有根据 `budget.used`、`context_limit` 或 `remaining_context` 分支处理。
- 该估算没有把 `provider.max_tokens` 作为“保留输出空间”计入。`remaining_context == 0` 既可能代表刚好用完，也可能已经超出，调用方无法据此作出安全判断。
- 工具执行产生的新 `tool_result` 会在同一个 Turn 中追加至 `ctx.messages`。下一次循环虽会重新**估算**，却不会重新压缩；而 `ContextEngine` 的抽象注释虽称其“每次 LLM 调用前”判断，实际调用点仍只有 Turn 构建阶段，接口承诺与实现不一致。
- Provider 的 context-length 错误目前会落入一般的 `Exception` 分支，除 JSON 解析和图片不支持外没有专属恢复策略。因此本项仍为“已确认，待改造”。

### 缺陷与影响

- 没有在**每次** LLM 调用前，按模型上下文窗口并预留输出 token 做硬性准入检查。
- 工具结果会在 Turn 内追加到 `ctx.messages`；后续请求模型前不会再次压缩或裁剪，长工具输出可能使上下文突然超限。
- 当前简单压缩器主要按保留消息条数处理尾部；`tail_token_budget` 尚未成为严格的 token 裁剪约束，单条超长消息仍可能保留。
- System Prompt、工具 JSON Schema、Skill、Memory、附件解析文本或当前用户输入本身过大时，仅压缩历史无法解决。
- Provider 返回 context-length / token-limit 错误时，Loop 目前没有专门分类、一次激进恢复、再明确返回 `context_overflow` 的闭环。

结果是：请求仍可能直接失败，用户只能得到一般性 LLM 调用失败，而不是可解释、可恢复的上下文超限结果。

### 改造方向

在每一次 LLM 请求之前执行统一的 `preflight_context_budget`：

```text
估算 system + tools + skills + memory + history + current user + reserved output
  → 未超限：调用 provider
  → 超限：按优先级裁剪，并重新估算
       旧工具输出 → memory 注入 → 低优先级 skill → 历史压缩/按 token 裁剪
       → 仍超限：不调用 provider，返回 context_overflow
```

Provider 仍返回超限错误时，应只进行一次更激进的恢复尝试；仍失败则持久化结构化错误和诊断信息。工具执行完成后也必须重新运行该预算检查。

### 完成标准

- 每次 provider 调用前都有可测试的硬性预算门，并预留输出 token。
- 工具结果追加后会重新检查预算。
- 能区分 `context_overflow` 与普通 provider/network 错误。
- 对超长单条消息可按 token 裁剪，而非只按消息条数保留。
- `/usage`、Turn Report 和错误事件能说明主要超限来源及采取的裁剪动作。

## AD-002：工具迭代额度耗尽时不会真正请求最终总结

**状态：** 已修改（待回归验证）。

**相关代码：** `src/personal_agent/agent/loop.py` 的工具执行分支与最终响应提取逻辑。

### 旧版行为

每次工具执行后，Loop 会递减：

```python
agent._iteration_budget -= 1
```

额度耗尽时，代码向 `ctx.messages` 追加一条用户消息（“请总结一下已完成的操作”），随后立刻 `break` 退出主循环。

### 缺陷与影响

这条总结请求从未被发送给 LLM。退出循环后，最终文本仅从最后一条 assistant 消息提取；此时最后一条消息实际是刚追加的 user 消息，因此 `final_response` 会是空字符串。

这与事件文案“达到迭代上限，要求模型总结”的意图不一致，用户可能看不到已完成工具操作的总结。

### 新版校正

最新版的 `agent/loop.py` 在 iteration budget 耗尽时改为直接追加一条 assistant 消息“已达到本轮处理迭代上限，已停止继续调用工具。”，因此最终提取的 `final_response` 不再为空。它仍未额外请求 LLM 根据工具结果生成自然语言总结；这属于可优化体验，而非原先的空结果缺陷。

### 改造方向

额度耗尽后，进入一个明确的“最终总结阶段”：

1. 禁止再执行工具；
2. 允许且只允许一次额外的 LLM 调用；
3. 让模型读取已经存在的工具结果并生成最终总结；
4. 若该调用失败，返回包含已执行工具摘要的降级结果，而不是空字符串。

该阶段应与普通工具迭代额度分开计数，以避免模型借总结请求继续调用工具。

### 完成标准

- 迭代额度耗尽时，用户始终得到非空、可解释的最终结果。
- 模型在最终总结阶段不能继续触发工具。
- 该路径具有“工具执行后额度耗尽”的回归测试。
- Turn Report 可标识本轮因 `iteration_budget` 进入最终总结阶段。

## AD-003：Session JSON 索引与 SQLite 活跃状态发生漂移

**状态：** 已确认，待改造。

**相关代码：** `src/personal_agent/gateway/session_store.py` 的 `save_transcript()`、`list_user_sessions()` 与 `expire_sessions()`。

### 当前行为

消息保存后，`save_transcript()` 只调用 SQLite 的 `update_last_active()`；内存中的 `SessionEntry.last_active_at` 和 `message_count` 没有同步更新，也不会重新写入 `sessions.json`。而会话列表排序、展示的活跃时间与过期清理判断，都读取 JSON 索引中的旧值。

### 缺陷与影响

- 持续活跃的会话在会话列表中可能排序错误、显示过期的活跃时间。
- 服务重启后，索引仍是创建/重置时的时间；`expire_sessions()` 可能删除实际上仍活跃的会话。
- JSON 索引与 SQLite 的同一业务事实存在两个不同版本，且没有修复/对账机制。

### 新版核验（`main` @ `7b1afd0`）

问题仍存在：`save_transcript()` 在 SQLite 写入后仅调用 `db.update_last_active()`；`SessionStore._index[session_key]` 内存对象的 `last_active_at`、`message_count` 未更新，`sessions.json` 也不会重写。`list_user_sessions()` 的排序与 `expire_sessions()` 仍直接使用这份 JSON 索引中的旧值。

新版 `write_json_atomic()` 已使用同目录临时文件、`fsync` 和原子替换，改善了**单个 JSON 文件**被写坏的概率；但它不解决 JSON 与 SQLite 的业务状态漂移。

### 改造方向与完成标准

将活跃时间和消息数确定为单一事实来源（推荐 SQLite），或在每次成功写入 transcript 后同步更新 `SessionEntry` 并原子写入索引。会话列表、过期策略和恢复逻辑必须使用同一份活跃状态；补充“多次写入、重启后列表排序、过期清理”的回归测试。

## AD-004：压缩会话重命名只更新根节点，压缩后代保留旧 session key

**状态：** 已确认，待改造。

**相关代码：** `src/personal_agent/gateway/session_store.py` 的 `rename_session()` 与 `create_compressed_session()`。

### 当前行为

压缩后，一个逻辑会话会有根 session id 和若干压缩后代 id。`rename_session()` 只更新索引根条目及根 id 对应的 SQLite `sessions.session_key`；压缩后代 SQLite 行不会更新。

### 缺陷与影响

重命名发生在压缩之后时，同一逻辑会话的 SQLite 数据会同时带有新旧 `session_key`。按 `session_key` 查询的 Turn Report、Tool Run 或运维诊断可能漏掉压缩后代的数据，造成审计和查询不完整。

### 新版核验（`main` @ `7b1afd0`）

问题仍存在且范围更明确：`rename_session()` 只对索引根条目的 `session_id` 调用 `db.update_session_key()`。压缩链后代的 `sessions.session_key` 未更新；`tool_runs` 与 `turn_reports` 表中冗余保存的 `session_key` 也没有更新。`create_compressed_session()` 刻意保留 JSON 索引指向根节点、依赖 `CompressionChain.resolve()` 找到后代，这一设计本身可以保留审计历史，但要求重命名必须按完整 lineage 级联更新。

### 改造方向与完成标准

重命名时通过压缩链取得完整 lineage，并在一个数据库事务内更新所有后代的 `session_key`，包括所有依赖该 key 的审计记录。补充“压缩 → 重命名 → 查询历史/Turn Report/Tool Run”的回归测试。

## AD-005：会话与压缩链持久化没有跨存储原子性或故障修复

**状态：** 已确认的可靠性缺口，待改造。

**相关代码：** `src/personal_agent/gateway/session_store.py`、`src/personal_agent/gateway/compression_chain.py`、`src/personal_agent/db/database.py`。

### 当前行为

普通 transcript 按单条消息逐条提交 SQLite；压缩时则依次创建 SQLite session、逐条写入压缩消息，最后再写入独立的 `compression_chain.json`。这些步骤之间没有事务，也没有启动时的一致性扫描与修复。

### 缺陷与影响

进程崩溃、磁盘错误或中途异常可留下：半轮消息、没有 chain 指向的孤儿压缩 session、chain 指向不存在 session，或 SQLite 与 JSON 索引不一致。部分损坏会在之后的 `resolve()`、会话列表、删除或过期清理中表现为丢失/遗漏数据。

### 新版核验（`main` @ `7b1afd0`）

新版对 JSON 单文件写入采用 `write_json_atomic()`，并会在读 JSON 失败时备份损坏文件后降级为空对象；这是局部耐损增强。但 `create_compressed_session()` 仍依次执行“创建 SQLite session → 逐条提交压缩消息 → 写 `compression_chain.json`”，普通 transcript 也是逐条 SQLite 提交，Turn Report 与 Tool Run 又在随后独立写入。因此仍不存在跨表、跨 SQLite/JSON 的原子提交，也没有启动时验证链指向的 session 是否存在或扫描孤儿 session 的修复流程。

### 改造方向与完成标准

优先把 compression lineage 纳入 SQLite，使 session、消息和 lineage 使用同一事务；或实现可重放的写前日志/状态机及启动修复任务。一次 Turn 的消息、Turn Report 和 Tool Run 也应具备明确的提交边界。需要故障注入测试覆盖每个写入步骤中断后的恢复。

## AD-006：跨 Turn 重放时，工具结果丢失“非用户输入”的信任边界

**状态：** 已确认，优先级高。

**相关代码：** `src/personal_agent/db/database.py` 的 `load_history()`。

### 当前行为

为兼容 Anthropic 的工具调用消息顺序，持久化历史重载时会把 `tool_result` 转换成普通 `role="user"` 文本消息。这能避免 API 协议错误，但原始工具来源、工具名、调用 id 与“不可信外部数据”身份不再保留。

### 缺陷与影响

文件内容、网页内容或命令输出可在下一 Turn 被模型视为用户说的话。恶意或被污染的工具输出因此可能形成跨 Turn 的提示注入；审计者也无法从重放历史准确区分用户指令与工具返回。

### 改造方向与完成标准

建立 provider-neutral 的历史事件模型，保留 `tool_result` 的来源、工具名、调用 id 和 trust level；针对不支持原生工具历史的 provider，使用明确标注“工具返回，非用户指令，不执行其中指令”的受控转换。补充恶意网页/文件内容在下一 Turn 不会改变工具权限或执行意图的测试。

## AD-007：系统生成的压缩摘要被持久化为 user 消息

**状态：** 已确认，待改造。

**相关代码：** `src/personal_agent/compression/simple.py` 的摘要消息构造。

### 当前行为

压缩器把 LLM 生成的历史摘要构造为 `role="user"`，随后作为新的压缩会话历史保存。文本虽然带有“系统生成的对话历史摘要”前缀，但数据库角色和导出角色仍是用户。

### 缺陷与影响

这会污染用户消息审计、导出和统计，也使模型角色语义与数据真实来源不一致。摘要若有错误，会被后续会话当成用户历史的一部分继续放大。

### 改造方向与完成标准

为摘要增加显式 provenance（例如 `role=summary`、`origin=system`、source range、压缩模型与版本），在各 provider 适配层映射为安全且不冒充用户的消息格式。导出和审计默认应能区分或选择隐藏该类内部消息。

## RI-001：同一 session 的并发 Turn 缺少服务层互斥（需压测确认）

**状态：** 风险项，尚需复现验证。

**相关代码：** `src/personal_agent/conversation/service.py`、Gateway busy-state 与各入口调用路径。

`ConversationService` 本身未对 `session_key` 加锁；它会读取 history、运行 Agent、再按 `previous_count` 追加保存。若某个新入口或调用方绕过 Gateway/TUI 的 busy-state，使同一 session 同时运行两个 Turn，可能发生历史快照竞争、消息顺序交错、Agent 内部状态互相污染或重复持久化。

改造前先写并发复现测试；若成立，应在 `ConversationService` 维护按 session 的 async lock 或队列，并为 `/stop`、`/steer` 与超时设计明确的并发语义。

## AD-008：工具中断状态是进程级全局变量，跨 session 泄漏

**状态：** 已确认，优先级高。

**相关代码：** `src/personal_agent/tools/executor.py` 的 `_interrupted`、`_active_tool_executions`，以及 `ConversationService.request_stop()`、`build_turn_context()`。

### 当前行为

工具执行器用模块级变量追踪中断：任何会话执行 `/stop` 都会调用 `interrupt_active_tool_executions()` 并设置全局 `_interrupted=True`。任一新 Turn 构建上下文时又会调用 `clear_interrupted()`，清除同一个全局标志。

**最新版核验：** `src/personal_agent/tools/executor.py` 仍定义模块级 `_interrupted` 与 `_active_tool_executions`；`ConversationService.request_stop()` 仍调用全局 `interrupt_active_tool_executions()`。新版已引入 per-session `SecurityContext`，但取消状态尚未随之会话化。

### 缺陷与影响

- Session A 的 `/stop` 可能使 Session B 正在运行的 bash、代码或其他工具提前返回 `interrupted`。
- Session B 开始新 Turn 又可能清除 Session A 的停止信号，导致 A 的长工具继续运行。
- `_active_tool_executions` 也是全局计数，无法表达“应停止哪一个 session/哪一次工具调用”。

这会破坏多用户 Gateway 的会话隔离。

### 改造方向与完成标准

将取消状态放入每个 Agent/Turn 的 `CancellationToken` 或 `asyncio.Event`，并将该 token 显式传递给 executor、确认等待与长运行工具。`/stop` 只能取消匹配 session 的 token；增加两个并发 session 分别执行长工具、其中一个 `/stop` 不影响另一个的回归测试。

## AD-009：工具桥接 `tool_call` 丢失原工具的权限与运行上下文

**状态：** 已验证。

**相关代码：** `src/personal_agent/plugins/builtin/tools/bridge/bridge.py` 的 `_tool_call()`；`tools/runtime_context.py`；`tools/executor.py`；`tools/execution_guard.py`；`tools/audit.py`。

### 旧版行为

`tool_call` 是给延迟暴露工具使用的桥接工具。外层 `tool_call` 先按自身的 `default` 类别通过 Executor；其 handler 再对目标工具调用 `execute_tool_call_result(...)`，但没有传入当前 `agent`、`hooks`、`event_sink` 或确认回调。内层在 `agent is None` 时跳过 execution policy、per-turn tool quota、destructive quota 和 grant 匹配，并可把 `web_fetch` 等 network 工具包装进低语义的 `tool_call`，绕开授权；Tool Run 事件和 Turn 统计也不完整。

### 新版校正与验证

- `_run_handler` 通过 ContextVar 注入 `agent` / `confirm` / `event_sink`；`_tool_call` 与 `dispatch_tool_call` 读取后传给内层 `execute_tool_call_result`。
- 嵌套 `ToolExecutionResult` 经 `preserve_nested_guard` 回写目标工具的 Guard 分类与授权元数据。
- `tool_call` 的 `counts_toward_quota=False`，外层不再双计 per-turn 配额；目标工具配额与直接调用一致。
- `audit_tool_result` 优先使用 result 上的 permission 字段，避免外层 wrapper decision 覆盖内层 network/write 分类。
- 已通过回归：`test_nested_tool_call_cannot_bypass_network_auth_in_ask_first`、`test_nested_tool_call_quota_matches_direct_on_success`、`test_nested_tool_call_audit_records_target_permission_category`，以及既有 confirm/denial 嵌套测试。

后续可选优化（非阻断）：搜索后把目标 schema 临时加入同 Turn 后续 provider 请求，减少对嵌套 `tool_call` 的依赖（见 AD-040）。

## AD-010：文件工具的资源上限与写入策略不一致

**状态：** 已确认，待改造。

**相关代码：** `src/personal_agent/plugins/builtin/tools/builtin/file_read.py`、`file_write.py`、`file_edit.py`。

### 当前行为

- `read` 先使用 `Path.read_text()` 把完整文件读入内存，再按 `MAX_READ_BYTES` 截断字符串；常量名是 bytes，但实际比较的是 Python 字符数量。
- `edit` 同样会先完整读取既有文件，之后才检查修改后的内容是否超过上限。
- `write` 有扩展名白名单及对应 precheck；`edit` 没有复用该白名单或 precheck，因此可编辑任意后缀的既有文本文件。

**最新版核验：** 上述资源上限与 `edit` 策略不一致的问题仍存在。新版已将 `Sandbox.check_path(path, access=...)` 接入当前 Tool 的 `SecurityContext`，使 handler 会再次校验 profile/精确 resource grant；这修复的是“外部路径经用户授权后仍在 handler 被静态 root 拒绝”的安全接线问题，并未解决字节上限、流式读取、共享写策略或原子写入问题。

### 缺陷与影响

超大日志、文本或伪装成文本的文件可造成不必要的内存占用乃至进程压力；`read` 的“50KB”提示不是实际字节限制。`edit` 与 `write` 同属 `write` 权限类别，却拥有不同的文件类型限制，导致策略难以推理和审计。

### 改造方向与完成标准

在读取前使用文件元数据执行真实字节上限检查，或使用流式/限量读取；对编辑同样在全量读取前限制源文件大小。将允许写入的文件类型、敏感路径规则和大小限制抽到共享文件策略，并同时用于 `write` 与 `edit`；写入采用临时文件加原子替换，避免异常时截断原文件。补充超大文件、非 ASCII 文本、未允许后缀和中途写入失败的测试。

## AD-011：文件记忆的当前 session/profile 使用模块级全局状态

**状态：** 已修改（待回归验证）。

**相关代码：** `src/personal_agent/plugins/builtin/memory/file/provider.py` 的 `_current_session_key`、`_profile_map`、`set_current_session()`。

### 旧版行为

文件记忆根据模块级 `_current_session_key` 决定当前 profile 目录（例如 `data/system/girlfriend/`）。Gateway 在 Turn 前设置这个全局变量，随后 `get_system_prompt_text()` 和 memory tool 通过它选择读取/写入目录。

### 缺陷与影响

并发 Session 时，Session B 设置全局 current session 可能使 Session A 的 system memory 注入或 memory 写入错误地落到 B 的 profile，导致用户画像、偏好或角色设定跨会话泄漏。

### 新版校正

最新版使用 `InternalMemoryStore.profile_for_session(session_key)` 纯函数式地解析 profile，并在 `MemoryScope(user_id, session_key, profile)` 中显式携带该上下文；`snapshot()`、写入和 consolidation 都传入 profile，写入锁也按 profile 分桶。不存在旧版 `_current_session_key` 模块级可变状态。仍需并发 profile 隔离测试，覆盖同一时刻 snapshot、consolidate 与人工 apply。

### 改造方向与完成标准

将 profile/session 选择放入每个 Agent 或每次 Turn 的显式 context，并传给 MemoryProvider；禁止 provider 依赖模块级当前 session。补充两个并发 profile 同时读取、写入和构建 system prompt 的隔离测试。

## AD-012：后台 Memory Review 复用主 Agent 的完整工具能力

**状态：** 已修改（待回归验证）。

**相关代码：** `src/personal_agent/memory/review.py` 的 `MemoryReviewService.review()`。

### 当前行为

Memory Review 在后台线程中复用主 Agent 的 transport 和完整 `agent.tools` 调用 LLM；若模型返回任意 tool call，服务会通过 `execute_tool_calls(..., agent=agent)` 执行它。约束“只保存记忆”仅存在于自然语言 prompt 中，而非代码级工具白名单。后台任务还可能和用户的下一 Turn 并发使用同一 Agent。

### 缺陷与影响

在 trusted/sovereign 等允许模式下，复盘模型受历史中的不可信文本影响时，理论上可请求非 memory 工具；同时共享 Agent 的权限、计数、取消状态和 transport 会产生并发状态污染。

### 新版校正

最新版 `memory/review.py` 的 `MemoryReviewService` 不再接收或复用主 Agent，也不调用 Tool Executor。它通过 `MemoryManager.review(messages, scope)` 走独立 memory router；job 只携带 `session_key`、`user_id`、消息与 `turn_id`。这已经移除了“后台 review 拥有主 Agent 完整工具能力”的结构性风险。仍需补测试，确认 router 使用的 LLM 提取链路没有任何通用工具执行出口，且不可信工具结果在提取提示中被安全标注。

### 改造方向与完成标准

为 Review 创建独立的受限 Agent/ExecutionContext，只暴露 `memory`（或更窄的内部 save API），不复用用户 Agent 的权限和可执行工具；Review 输入应明确标记不可信工具输出。增加测试断言复盘永远不能调用 write/bash/network，且 Review 与下一用户 Turn 并发时状态彼此隔离。

## AD-013：内建长期记忆写入后不会刷新缓存的 System Prompt

**状态：** 已修改（定期刷新，待优化与回归验证）。

**相关代码：** `src/personal_agent/plugins/builtin/memory/file/provider.py` 的 memory tool，以及 `src/personal_agent/agent/agent.py` / `agent/context.py` 的 `_cached_system_prompt`。

### 旧版行为

Agent 创建时会将 FileMemoryProvider 的 `data/system/*.md` 内容拼入 `_cached_system_prompt`。后续 Turn 只有在工具注册表变化导致 prompt cache 置空时才重建该 System Prompt。memory tool 写入 `MEMORY.md` 或 `USER.md` 后没有使当前 Agent 的 prompt cache 失效。

### 缺陷与影响

用户或 Memory Review 新保存的偏好/事实虽然已经写入文件，但同一 session 的缓存 Agent 在后续 Turn 仍可能继续使用旧 System Prompt；记忆往往要等到 Agent 被重建或服务重启才生效，行为与“已保存长期记忆”的预期不一致。

### 新版校正与剩余取舍

最新版 Agent 创建时 pin `InternalMemorySnapshot`；每个 Turn 在 `build_turn_context()` 中调用 `_maybe_refresh_memory_snapshot()`。达到 `memory.review.snapshot_refresh_turn_interval`（默认 20）后，系统重新读取 profile snapshot，只有 revision（Markdown 内容 hash）变化才使 `_cached_system_prompt` 失效并重建。`memory_buffer` 工具的 `refresh_snapshot` action 可立即重新 pin snapshot 并失效缓存。

这修复了旧版“同一缓存 Agent 永远不刷新”的缺陷，同时避免每次后台写入都破坏 provider prompt cache。剩余取舍是：自动 consolidation 后，当前 Agent 最多可能继续使用旧 Internal Memory 到下一个刷新间隔；若产品要求“用户刚确认的内部记忆必须下一 Turn 生效”，应让该写入事件精确通知受影响 Agent，或降低/可配置该间隔。需要覆盖定期刷新、强制刷新、内容未变不重建 prompt、不同 profile 隔离的测试。

### 改造方向与完成标准

为 MemoryManager/FileMemoryProvider 提供变更版本号或失效通知；成功写入/删除内建记忆后仅使受影响 Agent 的 system prompt cache 失效，并在下一 Turn 安全重建。补充“memory add → 下一 Turn prompt 包含新记忆”和 profile 隔离回归测试。

## AD-014：`memory_ingest` 绕过统一文件 Sandbox

**状态：** 已验证。

**相关代码：** 旧入口已删除；共享受控读取见 `src/personal_agent/tools/file_access.py`；`read` 工具见 `plugins/builtin/tools/builtin/file_read.py`。

### 旧版行为

`memory_ingest(path)` 直接将模型提供的路径交给 external memory provider，后者使用 `Path(file_path)` 读取文本、PDF 或 docx。该 ToolEntry 未设置 `precheck`、未调用 `Sandbox.resolve/check_path`，也未使用 `read` 权限类别。即使普通 `read` 会拒绝 sandbox root 外路径，模型仍可经由 ingest 读取并持久化任意本地文件。

### 新版校正与验证

- 产品方向不再恢复 Agent 可调用的 `memory_ingest`（知识 RAG 将作为独立插件）；当前 `memory` 工具仅支持 `add/search/list/delete/history`，无 `path`/`ingest`。
- 新增共享受控读取 seam：`resolve_readable_path` / `file_read_precheck` / `read_sandboxed_text` / `extract_sandboxed_document`。任何未来文件→记忆/RAG 摄取必须先经此 API，禁止 provider 接收裸路径。
- `read` 工具改为使用同一 seam，并挂上 Guard 前 `precheck`（`permission_category="read"`）。
- 回归：`tests/test_memory_ingest_sandbox.py` 覆盖工具未注册、`.env`/`.ssh`/root 外拒绝、workspace 允许、符号链接逃逸（环境允许时）、以及“裸 `Path.read_text` 会成功但共享 seam 必须拒绝”的对照。

### 改造方向与完成标准

为 ingest 使用与 read 相同的规范化路径、blocked-pattern 与 root/PathGrant 决策；ToolEntry 应使用 `permission_category="read"` 并在 Guard 前执行共享 file precheck。将读取和解析放到受控文件服务中，避免 provider 接收裸路径。增加 `.env`、`.ssh`、root 外文件、符号链接逃逸和允许 workspace 文件的回归测试。

## AD-015：Embedding 外部记忆缺少用户/session/profile 隔离

**状态：** 已修改（待回归验证）。

**相关代码：** `src/personal_agent/plugins/builtin/memory/embedding/provider.py` 与 `MemoryManager`。

### 旧版行为

EmbeddingMemoryProvider 将所有条目保存到同一份 `external_memories.json` 和 `external_embeddings.npy`，条目只包含 id、text、created_at。`prefetch(user_message)` 对全部向量做余弦相似度检索，没有携带或过滤 session key、platform user id、profile 或访问域。

### 缺陷与影响

多个 Gateway 用户共用同一个 external provider 时，用户 A 保存的偏好、事实或 ingest 文档片段可能因语义相似而注入用户 B 的 Prompt，形成跨用户隐私泄漏和行为污染。

### 新版校正

最新版以 `MemoryScope` 贯穿 `MemoryManager`、router、archive 与 provider；SQLite 的 observations、memories、FTS、review checkpoint 与 buffer 均使用 scope key 过滤。默认持久化 scope 是 `agent_id:user_id:profile`：同一用户同一 profile 的不同会话可共享长期记忆，不同用户或 profile 不会互相检索。Router 的运行态额外以 `(user_id, session_key, profile)` 隔离。仍需端到端测试验证 primary provider（如 Qdrant/Mem0）也严格使用相同 scope filter，且 session key 解析不会将不同平台用户错误归并。

### 改造方向与完成标准

Memory entry 必须携带 owner/scope metadata，并将 session/user/profile scope 显式传入 save、prefetch、search、delete；检索必须先执行访问域过滤再按相似度排序。默认 scope 应是 platform user 或 profile，跨用户共享只能显式授权。补充两个用户写入相似记忆而互不召回的隔离测试。
# AD-016：MemoryReview 只由 Gateway 启动，CLI 路径丢失后台复盘

**状态：** 已修改（待回归验证）。

- `agent/context.py::build_turn_context()` 无论入口都会按 `_memory_review_interval` 设置 `should_review_memory`；`agent/loop.py` 和 `ConversationService` 也会将该标志返回。
- 但唯一的 `MemoryReviewService.maybe_spawn()` 调用位于 `gateway/gateway.py::_handle_message_with_agent()`。CLI/TUI 直接调用 `ConversationService` 后没有等价的调度点，因此 `personal-agent chat` 虽会计数，却不会自动执行记忆复盘。
- 后果：同一配置在 `serve` 与 `chat` 两个入口的长期记忆行为不一致；而且复盘调度属于对话应用层却被绑定在某一适配器入口。
- 改造方向：将“成功 Turn 后是否启动复盘”的编排收敛到 `ConversationService` 或一个由 CLI 与 Gateway 共同调用的 Turn 后处理器；再以显式的会话/用户 scope 与受限的 review agent 执行（同时处理 AD-012）。

**新版校正：** `ConversationService.run_turn_input_events()` 在所有成功 Turn 持久化后调用 `memory_review_service.submit(...)`；CLI、TUI 和 Gateway 都复用该 Service，因此不再由 Gateway 独占触发。复盘间隔改由 archive checkpoint 的 `reviewed_turns` 判断，而非旧版 Agent 内存计数。

# AD-017：全局单槽 MemoryReview 会静默跳过其他会话

**状态：** 已修改（待回归验证）。

- `AppRuntime` 只创建一个 `MemoryReviewService`；其 `active`、`cancel_requested` 和去重签名均为服务全局状态。
- 当一个会话的后台 review 运行时，另一个会话触发 `maybe_spawn()` 会因 `self.active` 直接返回 `False`，既不排队也不重新设置该会话的 turn 计数；该次复盘因而永久丢失。
- 计数也在 `build_turn_context()` 的 Turn 开始阶段归零，而 `ConversationService` 仅在成功完成时才允许 review；恰好触发间隔的失败/中断 Turn 同样会吞掉一次 review。
- 多用户 Gateway 下还会使取消与健康状态跨会话混在一起。
- 改造方向：按会话/用户 scope 建立去重与队列（可设置全局并发上限），并将取消令牌绑定到单个 review job；不要用一个全局布尔值表达所有任务的状态。

**新版校正：** `MemoryReviewService` 改为 `asyncio.Queue` 加可配置 worker 并发（默认 2）；每个 session 通过独立 `asyncio.Lock` 串行，同一时间不同 session 可以被不同 worker 处理。review 成功后才以 `archive.set_checkpoint(... reviewed_turns=...)` 提交进度，因此失败或排队不会提前清除触发资格。仍需压测验证队列关闭、积压、重复 job 和异常重试语义。

## AD-018：LLM 请求计划的缓存分层尚未落实为供应商级缓存边界

**状态：** 已确认，低优先级性能/成本优化。

**相关代码：**

- `src/personal_agent/llm/base.py`：`LLMRequestPlan` 与 `BaseTransport.build_request_from_plan()`。
- `src/personal_agent/agent/loop.py`：`_build_request_plan()`。
- `src/personal_agent/plugins/builtin/llm/builtin/anthropic.py`：Anthropic 请求的 `cache_control`。
- `src/personal_agent/plugins/builtin/llm/builtin/chat_completions.py`：OpenAI-compatible 请求序列化。

### 当前行为

`LLMRequestPlan` 已在概念上区分 `stable_system`、`stable_tools`、`dynamic_context`、历史、当前用户消息和 `turn_tail`，并记录稳定前缀哈希等诊断数据。但是默认 `BaseTransport.build_request_from_plan()` 立即调用 `plan.to_messages()`，再按旧式 `build_request()` 序列化；该结构本身不会在协议层创建缓存断点或复用本地结果。

Anthropic Transport 仅为 System Prompt 的末个块添加 `cache_control: {type: ephemeral}`；工具 Schema、稳定历史和其他所谓稳定块没有显式缓存边界。OpenAI-compatible Transport 没有显式缓存字段，只依赖供应商可能提供的自动前缀缓存。每轮变化的 Memory Prefetch 位于历史之前，因此即使供应商支持按完整 messages 前缀复用，也会削弱后续历史前缀的稳定性。

### 新版对比旧版

新版新增 `turn_tail`，将当前用户消息后的工具调用/工具结果、Hook 追加上下文和无工具收尾指令纳入计划；旧版计划会遗漏这些内容，而 Transport 又优先使用计划构建请求，存在同一 Turn 工具结果未随请求发送的正确性风险。该问题已修复。

但“稳定/动态”分层及缓存哈希诊断在旧版已基本存在；新版尚未把它升级为可验证的、跨供应商一致的缓存编排能力。

### 改造方向与完成标准

为每个 Transport 明确缓存能力与断点策略：Anthropic 对符合限制的 System/Tools/稳定上下文设置明确的 cache control；兼容 API 仅在供应商文档确认支持时使用对应字段，否则标记为自动/不可控缓存。将动态 Memory 放在不破坏稳定前缀的位置，或只将真正稳定的块声明为可缓存。通过 Turn Report 同时记录请求计划哈希、实际 Provider 缓存读写 token 和缓存策略，使“计划稳定”与“实际命中”可区分、可测试。

## AD-019：受限子 Agent 的“研究”工具策略与隔离安全上下文冲突

**状态：** 已确认，待改造。

**相关代码：**

- `src/personal_agent/agents/runtime.py`：`READONLY_TOOLS`、`_execute_tools()`。
- `src/personal_agent/plugins/builtin/tools/builtin/delegate.py`：`_run_research()`。
- `src/personal_agent/security/evaluator.py`：`isolated_security_context()` 与资源权限检查。

### 当前行为

子 Agent 默认可选择 `web_search`、`web_fetch` 等只读工具；`run_research()` 也明确将两者放入 allowlist。然而真正执行工具时，`AgentRuntime._execute_tools()` 会创建 `isolated_security_context("read-only")`。该上下文的 `network_enabled=False`，且 approval policy 是 `never`；而 Web 工具都声明了 `permission_category="network"` 并生成 network resource requirement。结果是模型即使正确调用搜索或抓取工具，也会被 Executor 以 `resource_permission_denied` 拒绝。

### 新版对比旧版

新版把子 Agent 从旧的 `_destructive_allowed` 标记迁移到统一 `SecurityContext`，这是正确的安全接线改进：子 Agent 不再绕过统一 Executor 权限模型。但它把“只读”错误地等同于“无网络”，使原本宣传的 research 能力失效；旧版虽缺少统一资源控制，至少不会因这条新接线自动拒绝网络工具。

### 改造方向与完成标准

为子 Agent 定义独立、显式的最小权限 profile，例如 `delegated-research`：只允许网络 connect 与 workspace read，仍禁止写入、进程控制、递归委派和用户 session grant 继承。`run_research()` 使用该 profile；普通只读子 Agent 仍保持无网络。补充“研究 Agent 可搜索/抓取、代码审查 Agent 不可联网、两者均不可写入或递归委派”的回归测试。

## AD-020：子 Agent 的 `timeout` 不是整个 Run 的截止时间

**状态：** 已确认，待改造。

**相关代码：** `src/personal_agent/agents/runtime.py` 的 `AgentRuntime.run()`、`_execute_tools()`、`_coerce_schema()`。

### 当前行为与影响

`spec.timeout` 分别包裹首次 LLM 调用、工具后的最终 LLM 调用，以及可选 JSON schema 修复调用；工具执行本身不受同一个剩余时间预算约束。因此一个配置为 180 秒的 Run 最多可先等待 180 秒、执行工具、再等待最多 120 秒、再进行 schema 重试，真实运行时长明显超过声明的 timeout。取消只能取消当前 asyncio task，无法将已经交给外部进程/网络的底层工作统一纳入 deadline。

### 改造方向与完成标准

在 Run 创建时建立绝对 deadline，将每次 LLM 调用、工具执行和 schema 修复均限制为剩余时间；Executor 也应接收该 cancellation/deadline token。最终 Run、JSONL 审计记录和 UI 必须报告实际 deadline 触发原因。补充“多次 LLM 调用 + 慢工具不能超过总 timeout”的测试。

## AD-021：子 Agent 的 `output_schema` 只做了极浅层校验

**状态：** 已确认，待改造。

**相关代码：** `src/personal_agent/agents/runtime.py` 的 `_coerce_schema()`、`_extract_json()` 与 `_validate_schema()`。

### 当前行为与影响

当调用者提供 JSON Schema 时，系统会要求模型返回 JSON，并在失败后再请求一次。但 `_validate_schema()` 只在 schema 顶层 `type == "object"` 时确认结果是 `dict`，再检查 `required` 的键是否出现；不验证 `properties` 的字段类型、嵌套对象、数组项目、`enum`、`additionalProperties` 或其他约束。非 object schema 更会被直接判定为合法。

这意味着工具调用方若据此相信“输出已符合 schema”，仍可能收到类型错误或结构不完整的数据；后续自动化分支会在更晚的位置失败，且难以追溯到子 Agent 的契约违约。

### 改造方向与完成标准

使用标准 JSON Schema validator（或明确限制并实现支持的子集），在模型输出和修复输出后执行完整验证；失败时记录 validation errors，而不是仅返回截断原文。补充嵌套类型、数组、枚举、额外字段与非 object schema 的测试。

## AD-022：Workflow Engine 与 primitives 使用模块级全局运行上下文

**状态：** 已确认，优先级高。

**相关代码：**

- `src/personal_agent/workflow/engine.py`：`_engine_call_fn`、`_engine_tools` 与 `setup_engine()`。
- `src/personal_agent/workflow/primitives.py`：`_call_fn`、`_tools`、`_phases`、`_logs` 与 `_reset_context()`。
- `src/personal_agent/agent/factory.py`：每次创建 Agent 后调用 `setup_engine()`。

### 当前行为与影响

Workflow Engine 的 LLM transport、工具列表和最大 token 是进程级全局变量；任何 session 创建/重建 Agent 都会覆盖它。每次 `run_workflow()` 又会重置 primitives 的全局 call_fn、tools、phase 和 log 列表。两个 workflow 并发运行时，后启动的 run 可覆盖前一 run 的上下文和进度，导致模型/工具配置串用、日志混杂或返回的 phases 不属于该次执行。不同 session 的工作流也不携带各自的 SecurityContext、取消 token 或用户身份。

### 改造方向与完成标准

创建显式的 `WorkflowRunContext`（transport、工具快照、SecurityContext、deadline、事件 sink、run id），由 `run_workflow()` 作为参数传入 workflow 与 primitives；删除模块级可变运行态。每次执行保存独立日志/phase，支持并发和取消。补充两个不同 session、不同 tool snapshot 的并发 workflow 隔离测试。

## AD-023：内建 Review Workflow 没有证据获取闭环，且重复使用浅层 Schema 校验

**状态：** 已确认，待改造。

**相关代码：**

- `src/personal_agent/workflow/primitives.py`：`agent()`、`_validate_schema()`。
- `src/personal_agent/plugins/builtin/workflows/review/workflow.py`：`review_workflow()`。

### 当前行为与影响

`review_workflow()` 仅把用户提供的文件路径拼进 prompt；`primitives.agent()` 虽把完整 tools schema 传给 LLM，却只取 `response.text`，完全忽略 `response.tool_calls`，也不会进入 Tool Executor。因此模型没有被保证实际读取这些文件、检索仓库或验证行号，代码审查结果可能建立在猜测上。其 `FINDING_SCHEMA`/`VERDICT_SCHEMA` 还依赖 primitives 自己的浅层 `_validate_schema()`，同样只验证顶层必填键，不能保证 `findings` 数组内容、severity 枚举或 `is_real` 布尔值正确。

### 改造方向与完成标准

让 workflow 使用受限的、可审计的子 Agent 执行循环，至少允许并要求 `read/grep/glob` 获得证据；将读取到的片段、路径和行号作为 finding 的必需证据字段。复用 AD-021 的完整 Schema validator。若模型未提供工具证据，workflow 应标记结果为未验证而非“已确认”。补充“模型返回 tool_call 后确实执行 read”“无证据 finding 被降级”“错误 severity 类型被拒绝”的测试。

## AD-024：Review Workflow 的验证阶段缺少扇出与成本配额

**状态：** 已确认，待改造。

**相关代码：** `src/personal_agent/plugins/builtin/workflows/review/workflow.py` 的 finder 结果处理与 `pipeline(unique, verify_stage)`；`workflow/primitives.py` 的 `parallel()`、`pipeline()`。

### 当前行为与影响

第一阶段的 dimension 数量有固定集合，但每个 finder 可以返回任意多条 finding。去重后，验证阶段会为每条 finding 通过 `pipeline()` 并发创建一次 LLM 调用，没有最大 findings、每工作流并发上限、总 token 预算或优先级截断。引擎只有 600 秒整体 timeout；在到达超时前仍可能产生大量并发请求、速率限制或成本尖峰，且部分已执行调用没有结构化 checkpoint/取消审计。

### 改造方向与完成标准

为 WorkflowRunContext 增加 `max_parallel_agents`、`max_findings_to_verify`、总输入/输出 token 和绝对 deadline；验证阶段按风险优先级分批并发，达到配额后在结果中明确标注未验证项。补充大量 finder 输出时并发数受限、配额耗尽可解释、取消后不再启动新验证调用的测试。

## AD-025：配置快照无法准确区分 `.env` 与进程环境变量来源

**状态：** 已确认，低优先级可观测性问题。

**相关代码：** `src/personal_agent/config_loader.py` 的 `ConfigLoader.load()`、`_resolve_raw_value()` 与 `_profile_source()`。

### 当前行为与影响

新版先构造 `environment = {**raw_env, **os.environ}`，因此实际优先级正确：进程环境变量会覆盖 `.env`。但随后将这个合并字典传给 `_resolve_raw_value()`；只要变量存在，就把 `resolved_source` 标为 `.env`。`profiles` 的来源判断也复用同一合并字典。结果是仅由 Docker、CI、PowerShell `$env:...` 等注入的值，在 `ConfigSnapshot`、`doctor` 输出中会被误报为来自 `.env`。

值本身不会错误，却会使部署排障、配置审计和“为什么当前模型/权限与文件不同”的追溯失真。

### 改造方向与完成标准

分别保留 `process_env`、`.env` 和合并后的 effective environment；按 `override → process_env → .env → config.yaml → default` 返回真实来源。诊断应脱敏展示实际来源，并补充“仅 `.env`、仅进程环境、两者冲突、profiles JSON 覆盖”的测试。

## AD-026：Gateway 的动态会话切换路由不持久化

**状态：** 已确认，待改造。

**相关代码：** `src/personal_agent/gateway/session_router.py`、`gateway/gateway.py` 的启动与 `_GatewayCommandRuntime`。

### 当前行为与影响

`/session switch`、`/session rename` 只修改 `GatewaySessionRouter.overrides` 这一内存字典。Gateway 启动时仅从静态 `config.session_override` 重新加载；运行中产生的切换/重命名映射不会写入 JSON 或 SQLite。服务重启后，同一个平台用户会回到 `base_key`，而不是上次选定的命名会话。会话数据虽然仍在，但活跃会话选择被静默丢失，容易造成用户在错误上下文继续对话。

### 改造方向与完成标准

将“源 chat 的当前活动会话”作为独立持久化状态（至少含 platform/chat/user、target session key、更新时间），并在重启后恢复；`/session delete` 同步清理映射。明确区分静态管理员 override 与用户运行时选择。补充“切换 → 重启 → 仍路由到目标会话”“删除目标会话 → 回退 base key”的测试。

## AD-027：Gateway 命名会话 key 丢失 `chat_id`，可能跨群聊共享上下文

**状态：** 已验证。

**相关代码：** `src/personal_agent/gateway/session_router.py` 的 `base_key()` 与 `named_key()`。

### 旧版行为与影响

默认基础 key 为 `platform:chat_id:user_id`，因此同一用户在不同群聊默认隔离；但 `/session switch <name>` 生成的命名 key 是 `platform:name:user_id`，没有 `chat_id`。同一用户在两个群聊中选用相同名称时，会进入同一个 SessionStore 会话，也共享同一 `SecurityStateStore` 状态、MemoryScope 的 session key 以及可能的工具授权。

### 新版校正与验证

- 命名会话改为按聊天隔离：`platform:chat_id:name:user_id`（名称中的 `:` 会被清洗为 `_`）。
- 基础会话仍为 `platform:chat_id:user_id`；overrides 仍以 base key 为索引，因此两个群聊的同名切换互不影响。
- 回归：`test_named_sessions_with_same_name_are_isolated_across_chats`、`test_gateway_named_session_does_not_leak_across_chats`。

若未来需要显式的用户级跨聊天共享会话，应另设 session 类型与 UI/授权策略，而不是回退到缺少 `chat_id` 的命名 key。

## AD-028：Slash Command 元数据注册表与实际分发逻辑双维护

**状态：** 已确认，低优先级可维护性问题。

**相关代码：** `src/personal_agent/commands/registry.py` 与 `commands/runtime.py::handle_slash_command()`。

### 当前行为与影响

`CommandSpec` 已声明命令名称、别名、参数、可用入口、`mutates_state` 和 `requires_agent`，供帮助文本、TUI 自动补全和协议元数据使用；但实际执行仍由 `handle_slash_command()` 中按字符串逐项 `if` 分发，不读取或强制这些字段。因此新增/修改核心命令必须同时改两处，且 `available_in`、参数定义或“需要 Agent”仅是展示信息，不是运行时契约。元数据与处理器漂移时，前端可能展示不可用命令，或遗漏危险命令的状态变更标记。

### 改造方向与完成标准

让注册表持有处理器标识、解析器与执行前置条件，或至少在启动/测试时校验每个核心 `CommandSpec` 都有唯一 handler、handler 的入口范围与 metadata 一致。对 mutating command 增加统一审计/确认 hook。补充注册表—dispatcher 完整性测试。

## AD-029：事件协议只在测试中校验，运行时可产生不完整事件

**状态：** 已确认，低优先级可观测性问题。

**相关代码：** `src/personal_agent/conversation/events.py` 的 `emit_event()`、`validate_event_contract()`；`src/personal_agent/tui/renderer_base.py`；`tests/test_event_protocol.py`。

### 当前行为与影响

`ConversationEventType`、`EVENT_SCHEMAS` 和 `Renderer._DISPATCH` 已有完整性测试，且新版为 `tool_decision`/`tool_end` 增加了审批方式、请求资源、结构化产物摘要和结果元数据，前端能更准确解释工具调用。不过 `validate_event_contract()` 的注释已明确其用途是“tests and future debug tooling”：生产路径的 `emit_event()` 只创建并转发事件，不会检查 schema 中的必填字段。因此某个新事件发射点漏传 `tool_use_id`、`error` 等字段时，运行时仍会继续；问题会延后表现为 TUI/Gateway 展示缺信息、工具运行记录不完整或诊断统计失真。

这不是安全执行边界问题：Executor 的实际授权与执行不依赖事件；它是审计与界面契约的可靠性问题。高频 delta 不宜逐条做昂贵校验，但低频生命周期、工具和错误事件应具备可选的严格检查能力。

### 改造方向与完成标准

为 `EventRecorder` 或调试/测试配置提供可选 strict mode：对非 delta 事件调用 `validate_event_contract()`，开发环境抛出明确异常，生产环境至少记录结构化诊断并保留事件。可进一步将 `EventSchema` 作为唯一事实来源生成 Renderer 的默认分派，或继续保留显式分派表但维持现有完整性测试。补充“实际 Agent Loop/Executor 发出的每个非 delta 事件均通过校验”集成测试，以及“生产宽容模式不会让事件校验故障中断用户回合”的测试。

## AD-030：平台聊天锁的 LRU 淘汰可移除仍被占用的锁

**状态：** 已确认，优先级中（并发一致性）。

**相关代码：** `src/personal_agent/platforms/core.py` 的 `BasePlatformAdapter._process_message_background()`、`_get_chat_lock()`；平台适配器基类的消息队列。

### 当前行为与影响

BasePlatformAdapter 通过 `chat_id -> asyncio.Lock` 保证同一个 chat 中的消息在进入 Gateway、调用 Agent、发送回复的整段流程内串行；这比按 `platform:chat_id:user_id` 的 session 队列范围更宽，能避免群聊内不同用户的回答交叉。为了控制内存，`_get_chat_lock()` 把锁放入容量有限的 `OrderedDict`；达到 `platform_chat_locks_maxsize` 时直接 `popitem(last=False)` 淘汰最久未使用项。

淘汰逻辑不检查该锁是否 `locked()`。如果大量不同 chat 在短时间内活跃，最旧 chat 的任务仍持有锁时也可能被移除；该 chat 随后另一位用户发来消息时，因 session key 不同而不会进入同一用户队列，并会创建一把新的 chat lock。新旧两把锁彼此独立，于是两个回合可以并发运行并向同一群聊交错发送结果，破坏了代码试图提供的 per-chat serialization。现有测试仅验证配置值被读取，未覆盖锁满且旧锁仍占用的情形。

### 改造方向与完成标准

锁缓存满时只淘汰未锁定且没有待处理消息的 LRU 项；若全部锁正在使用，允许短暂超过缓存上限，或使用带引用计数/生命周期清理的 lock entry，并在任务结束后再回收。队列和锁的 key 应继续以 `platform + chat_id` 为维度。补充回归测试：容量为 1 时，chat A 正在运行、chat B 到来、chat A 的另一用户再到来，必须仍然等待同一把 A 锁；并验证空闲锁最终可被回收且缓存不会无界增长。

## AD-031：Hook 超时不覆盖同步回调，插件可阻塞整个事件循环

**状态：** 已确认，优先级中（插件可靠性/可用性）。

**相关代码：** `src/personal_agent/hooks/manager.py` 的 `HookManager._execute()`；`hooks/specs.py` 的每类 Hook 默认 timeout。

### 当前行为与影响

HookManager 允许 callback 返回同步值或 awaitable。`_execute()` 先在事件循环线程直接执行 `registration.callback(envelope)`，仅当返回值已被识别为 awaitable 时才调用 `asyncio.wait_for(..., timeout=...)`。所以 timeout 能限制异步 Hook 的等待时间，却无法限制同步 Hook 内的 `time.sleep()`、同步网络/磁盘 I/O、CPU 密集计算或死循环；它们会在返回前阻塞整个 asyncio loop。

这使 Gateway 消息处理、工具授权/执行、TUI 刷新和所有其他 session 的协程都可能停顿。尤其 `PreToolUse` 被定义为 fail-closed，但同步 Hook 卡死时既不会安全拒绝，也不会触发 timeout 诊断。现有测试覆盖异步 Hook 的优先级与失败行为，未覆盖阻塞同步 callback。

### 改造方向与完成标准

明确 Hook 合约：推荐只接受 async callback；若保留同步 callback，必须将其放到受限线程池/进程池执行，并以 `wait_for` 包裹，同时规定取消、资源上限和线程池饱和时的 fail-open/fail-closed 语义。对于安全关键 `PreToolUse`，超时应产生可审计的拒绝，而不是让整个服务无响应。补充阻塞同步 Hook 不阻塞其他 session、超时统计正确、PreToolUse 超时被拒绝且 Gateway observer 超时只记录告警的测试。

## AD-032：原生多图输入没有回合级载荷/成本预算，token 估算过于粗糙

**状态：** 已确认，优先级中（可靠性/成本控制）。

**相关代码：** `src/personal_agent/attachments/store.py` 的单附件大小限制；`src/personal_agent/multimodal/processor.py` 的 `_native_image_block()`；`src/personal_agent/llm/token_counter.py` 的 `IMAGE_INPUT_TOKEN_ESTIMATE`；`src/personal_agent/agent/context.py` 的压缩预算。

### 当前行为与影响

附件缓存会对单个 image/audio/video/file 限制字节数，provider 也可声明单图 `max_image_bytes`；但系统没有每个 turn 的最大附件数、总原始字节、总 base64 字节、总像素或总视觉 token 配额。原生图片路径会把每个完整文件读入内存并编码为 `data:<mime>;base64,...`，随后直接放进 LLM 请求。多张各自合法的图片可以累加成远超单次 HTTP 请求、供应商视觉输入限制或可接受成本的负载。

与此同时 `count_messages_tokens()` 无论图片尺寸、分辨率、provider 规则或 data URL 长度如何，均固定按每张 1500 tokens 计入上下文预算。因而压缩/诊断可能显示预算充足，而实际请求体已经很大或被 provider 拒绝。当前 provider 拒绝图片后只会剥离所有 image block 并重试，不会保证已有 OCR/图片描述可替代原始视觉信息，用户问题可能悄然退化为无图回答。

### 改造方向与完成标准

增加多模态 turn budget：最大附件数、总原始字节、总编码后字节、最大像素/分辨率和 provider 专属视觉 token 估算；在构建 native block 前逐项裁决，并把拒绝/降级原因写入 diagnostics。优先缩放/压缩图片或改走文字化，不能安全容纳时明确提示而非静默删除内容。请求计划与 context budget 应分别报告文本 token、估计视觉 token 和实际 HTTP payload 大小。补充“多张单图均合规但总量超限”“高分辨率图视觉预算超限”“provider 拒图后有可见的文字降级或明确失败说明”的测试。

## AD-033：原生图片输入在会话持久化后丢失，后续回合无法重放其语义

**状态：** 已确认，优先级中（会话连续性）。

**相关代码：** `src/personal_agent/multimodal/processor.py` 的 native image block；`src/personal_agent/agent/finalize.py::unpack_message()`；`src/personal_agent/db/database.py::load_history()`。

### 当前行为与影响

native 图片以 `image_url` content block 仅供本次 LLM 请求使用。保存 transcript 时，`unpack_message()` 只提取 `type == "text"` 的块，明确忽略 `image_url`；加载历史时也只重建纯 text message。这样避免把完整 base64 图片复制进 SQLite（这是正确的隐私与容量选择），但 native 模式下 `ProcessedAttachment` 本身没有 `summary_text`：用户的历史消息最终只留下原始提示词，例如“帮我描述这张图”，图像和其可复用描述均不存在。

下一轮或进程重启后，模型无法理解“图中左侧的人”“继续比较刚才两张图片”等指代；若上一轮 assistant 答复不恰好覆盖所需视觉事实，连续对话会退化。现有测试验证 native block 创建，却没有验证 native 图片回合保存并重新加载后的上下文完整性。

### 改造方向与完成标准

定义附件历史投影，而不是持久化原始 data URL：保存稳定附件 id、hash、名称、处理状态和一个受长度限制的、明确标注来源的文字摘要/视觉描述；必要时保留本地缓存引用并在明确权限、有效期和可用性条件下支持再次加载。native 图片应可选地异步生成可持久化描述，或至少在历史中写入“图片曾参与该回合、不可重放”的结构化占位符，避免静默丢失。补充“native 图片 → 保存 → 新回合/重启 → 历史保有可理解摘要”“附件缓存被清理时仍有安全的文字投影”“原始 base64 不写入 SQLite”的测试。

## AD-034：Skill 的 `triggers` 元数据没有接入 slash 命令解析

**状态：** 已确认，低优先级功能正确性/可维护性问题。

**相关代码：** `src/personal_agent/skills/entry.py` 的 `SkillEntry.triggers`；`skills/registry.py::_entry_from_file()`；`commands/runtime.py::_prepare_skill()`；内置 Skill 注册。

### 当前行为与影响

SkillEntry 和 SKILL.md frontmatter 都可以声明 triggers，例如 `python-expert` 声明 `/python`、`/py`，`git-workflow` 声明 `/git`。但 `_prepare_skill()` 只把用户输入去掉 `/` 后的第一个词直接作为 skill name 执行 `skill_registry.load(skill_name)`；Registry 没有 trigger → name 索引，整个源码中也没有读取 `entry.triggers` 用于匹配。因此实际可用的是 `/python-expert`、`/git-workflow`、`/shell-guide`，而宣传的 `/python`、`/py`、`/git`、`/bash` 都不会注入 Skill，随后还可能落入普通的“未知命令”处理。

现有所谓 `/python` 端到端测试绕过了命令解析，直接调用 `skill_registry.load("python-expert")`；另一个测试仅断言 triggers 字段存在，无法发现这一行为差异。

### 改造方向与完成标准

在 Registry 建立规范化 trigger 索引，注册时拒绝与核心命令、插件命令或其他 Skill 冲突的 trigger；`_prepare_skill()` 应先按精确 skill name、再按 trigger 解析，并明确记录最终选择的 Skill。帮助文本和自动补全从同一索引生成。补充 `/python`、`/py`、`/git` 成功注入、名称与 trigger 冲突被拒绝、未知 slash 命令仍按原语义处理的集成测试。

## AD-035：显式 Skill 全文只出现在本 Turn 的第一次 LLM 请求

**状态：** 已确认，优先级中（Agent 行为一致性）。

**相关代码：** `src/personal_agent/commands/runtime.py::_prepare_skill()`；`src/personal_agent/agent/context.py`；`src/personal_agent/agent/loop.py::_build_api_messages()`。

### 当前行为与影响

用户以 `/skill-name <任务>` 激活 Skill 后，系统将全文放进 `agent._pending_skill_injection`，本 Turn 的首次 `_build_api_messages()` 把它作为 prefix user message 注入，然后立即执行 `ctx.skill_injection = None`。如果模型第一次请求调用工具，后续 while-loop 会重新构建 API messages；这些请求包含持久化消息、工具调用/结果、所有 Skill 摘要、Memory 和 Hook 上下文，但不再包含该 Skill 的全文。

LLM 请求彼此无状态，工具结果本身也不会携带 Skill 指令。因此依赖完整步骤、输出格式、安全约束或验收标准的 Skill，可能在“读取/检索 → 工具结果 → 最终回答”阶段失效；模型只能依赖首次请求时的隐式记忆。代码注释把这一行为称为“injected ONCE”，说明这是当前明确策略，但没有说明其对多步 Agent loop 的语义后果。

### 改造方向与完成标准

将 Skill 注入策略显式化：短摘要可每次请求常驻，全文可以在整个 Turn 内常驻，或由稳定的“Skill 已激活 + 可重新加载”机制保证每个工具后的 LLM 请求可获得必要约束。为避免上下文成本，可将全文拆成 immutable instructions 与一次性任务输入，并在 RequestPlan 中标出稳定段。补充“激活有输出格式约束的 Skill → 首次请求调用工具 → 第二次请求仍遵守约束”的集成测试，并在 `/usage` 中展示当前激活 Skill 的注入策略与 token 成本。

## AD-036：前台 `bash` 与 `execute_code` 在截断前会无界缓存子进程输出

**状态：** 已确认，优先级高（可用性 / 资源耗尽）。
**相关代码：** `src/personal_agent/plugins/builtin/tools/builtin/bash.py::_bash()`、`_decode_and_truncate()`；`src/personal_agent/plugins/builtin/tools/builtin/execute_code.py::_execute_code()`。

### 当前行为与影响

两个前台工具均先通过 `proc.communicate()` 读完 stdout 和 stderr，随后才把返回给模型的文本截断为 `bash` 的 4000 字符或 `execute_code` 的 8000 字符。截断因此只是展示与上下文层的限制，不是进程 I/O 的资源上限：在 60/120 秒内持续输出大量数据的命令或 Python 程序，仍会先在 Agent 进程内存中积累完整字节串，造成内存压力甚至 OOM。

相比之下，`process_start` 的后台路径已经由两个 `_reader()` 分块读取，并在 `_append_output()` 中只保留每个流最后 4000 字符；前台路径与其资源语义不一致。

### 改造方向与完成标准

抽取有字节上限的流式 reader：并发消费 stdout/stderr，固定保留尾部（或明确的首尾窗口）并记录截断字节数；达到硬上限后继续排空管道，或按策略终止子进程，不能再把完整输出留在内存。超时、用户取消和异常退出也必须安全等待 reader 收尾。补充大于上限数百倍的 stdout/stderr 回归测试，验证返回截断标记正确且峰值缓存量受限。

## AD-037：Windows 上的“终止进程树”只杀死直接子进程，且 Python 执行未响应 `/stop`

**状态：** 已确认，优先级高（进程生命周期 / 会话取消）。
**相关代码：** `src/personal_agent/plugins/builtin/tools/builtin/bash.py::_kill_process_tree()`、`_bash()`；`src/personal_agent/plugins/builtin/tools/builtin/execute_code.py::_execute_code()`；`src/personal_agent/tools/executor.py::interrupt_active_tool_executions()`。

### 当前行为与影响

`_kill_process_tree()` 在 Unix 使用 `killpg()`，但 Windows 分支仅调用 `proc.kill()`。前台 shell 和后台 `process_kill` 都可能只结束 `cmd`/shell 本身，未等待或终止由它启动的子孙进程；函数名承诺的“进程树”语义在 Windows 上并不成立。`execute_code` 的超时分支同样只执行 `proc.kill()`。

此外，`bash` 在每秒轮询中会检查 Executor 的中断标志，而 `execute_code` 只执行一次 `asyncio.wait_for(proc.communicate(), timeout=...)`；用户执行 `/stop` 后，Python 代码仍可能继续占用最长 120 秒。全局中断状态的跨 session 问题已由 AD-008 记录，此处是工具本身未接入取消与 Windows 子进程清理的额外缺口。

### 改造方向与完成标准

为每次执行建立可取消的、归属于该 turn/session 的进程管理对象。Windows 使用 Job Object 或受控 `taskkill /T /F` 等经验证方案，Unix 保持独立进程组；超时、`/stop`、异常清理统一走同一个“终止整个树并等待收尸”的路径。`execute_code` 也应以短轮询或取消 token 响应当前 turn 的停止请求。补充 Windows 条件测试：父进程启动子进程后超时/停止，子进程不再存活；以及 `execute_code` 收到停止后在短时间内返回 interrupted。

## AD-038：`execute_code` 被标为“sandboxed”，但未受到文件、网络或进程能力沙箱约束

**状态：** 已修改（已验证：当前未提供真实 OS 隔离时 fail-closed）。
**相关代码：** `src/personal_agent/plugins/builtin/tools/builtin/execute_code.py`；`src/personal_agent/tools/entry.py::ToolEntry`；`src/personal_agent/security/evaluator.py::prepare_tool_call()`、`_builtin_resources()`；`src/personal_agent/tools/execution_guard.py::fallback_tool_category()`。

### 当前行为与影响

### 最新修改（`codex/ad-038-secure-code-runner`）

项目尚未实现可验证的 Windows/Linux 代码运行隔离 Adapter，因此不能安全地把“临时工作目录 + 过滤环境”当作沙箱。本次改造删除了原先直接创建 Python 子进程的实现：`execute_code` 仍会注册，以便 Agent 和审计系统得到明确结果，但 handler 与 hard precheck 都会返回“未提供 OS-level code sandbox，工具已禁用”。这使任何工具授权或 `full-auto` 模式都无法重新启用当前用户权限下的任意 Python 执行。

ToolEntry 现明确声明 `permission_category="bash"`、`risk_level="high"`、`approval_mode="prompt"`、不可并行且为 destructive；描述不再承诺“sandboxed”或“不能访问 agent files”。未来重新启用必须先实现真实隔离 Adapter、能力探测和本条完成标准中的测试，不能只删除 precheck。

`execute_code` 仅创建临时 `cwd`、过滤环境变量并用 `sys.executable -c` 启动 Python。临时工作目录并不会阻止 `open(r"C:\\...")`、`pathlib.Path(...).read_text()`、`socket`、`subprocess` 或其他绝对路径/网络/进程能力；该进程仍拥有运行 Friday 用户的 OS 权限。其注册又未设置 `permission_category`、`risk_level`、`precheck` 或 `resource_resolver`，所以 `ToolEntry` 默认得到 `permission_category="default"`，`prepare_tool_call()` 也得不到任何资源需求；内核的 SecurityContext 无从对代码实际访问的文件或网络目标做授权判断。

因此工具描述中“isolated temp directory / no access to agent files”的安全承诺不成立，并且它可绕过 `read`、`write`、`bash`、网络工具各自的路径白名单、资源授权和命令预检。这不是把 `bash` 包装得更安全，而是一个未被 OS 沙箱隔离的任意代码执行入口。

### 改造方向与完成标准

在真正实现隔离前，移除“sandboxed / 无法访问 agent files”的描述，并至少将该工具设置为高风险、显式确认、不可并行，且默认在 read-only/ask-first 安全模式禁用。长期方案是在独立受限账户/容器/Job Object 或平台 sandbox 中执行，使用只读输入挂载与明确可写输出目录，默认关闭网络、限制 CPU/内存/进程数/磁盘，并将需要访问的路径与网络目标建模为可审计的 `ResourceRequirement`。补充安全回归测试：默认策略下绝对路径读取、任意网络、派生进程均被拒绝；仅在显式授权和真实隔离能力可用时才允许受限操作。

## AD-039：`bwrap` 的“filesystem isolated”实际仅限制写入，仍可读取整个宿主文件系统

**状态：** 已确认，优先级中（Linux 部署的隔离语义 / 机密读取）。
**相关代码：** `src/personal_agent/tools/process_sandbox.py::build_process_launch()`、`process_sandbox_snapshot()`。

### 当前行为与影响

Linux 且 `bwrap` 可用时，启动参数先执行 `--ro-bind / /`，随后只对 `writable_roots` 和当前 `cwd` 追加可写的 `--bind`。这能阻止进程写入其他宿主目录，但整个 `/` 仍作为只读文件系统暴露在 sandbox 内；因此 `filesystem_isolated=True` 不能解释为“只能看到 sandbox roots”，更不能解释为“无法读取宿主的配置、源码或其他可由当前 OS 用户读取的敏感文件”。

进程命令白名单和路径预检可降低某些直接读取路径的风险，但它们不是通用的 OS 文件可见性边界；特别是任何允许解释器、间接文件访问或未来扩展的命令都会依赖这一误解而扩大风险。`process_sandbox_snapshot()`/`doctor` 若仅报告“filesystem isolated”，部署者也无法分辨它是读写隔离、仅写隔离，还是完全不可用。

### 改造方向与完成标准

把隔离能力拆成显式的 `read_scope`、`write_scope`、`network_isolated` 与资源限制状态，诊断应如实显示“host root read-only mounted”。若产品承诺只允许读取 sandbox roots，应构造最小根文件系统：仅挂载运行时所需解释器/共享库、受控只读输入、显式可写目录和必要设备，而非把 `/` 整体挂入。补充集成测试：bwrap 模式下允许目录可写、未授权宿主路径不可读（或在仅写隔离模式下明确标为可读而非声称隔离）。

## AD-040：工具发现桥接没有动态补充下一次 LLM 的工具 Schema，却要求模型直接调用隐藏工具

**状态：** 已确认，优先级中（跨 Provider 工具协议可靠性）。
**相关代码：** `src/personal_agent/tools/registry.py::_assemble_with_bridge()`、`dispatch_tool_search()`；`src/personal_agent/plugins/builtin/tools/bridge/bridge.py`；`src/personal_agent/agent/agent.py::_refresh_tools()`；`src/personal_agent/agent/context.py::build_turn_context()`。

### 当前行为与影响

当存在非核心（deferrable）工具时，Registry 只把 `tool_search`、`tool_describe`、`tool_call` 三个 bridge schema 传给模型；搜索结果会在 tool result 文本中带回隐藏工具的 name 与 input schema。bridge 的说明随即要求模型“直接按隐藏工具名调用，不要用 `tool_call`”。

但 Agent 的 `tools` 只会在 Registry `generation` 改变时由 `_refresh_tools()` 重建；一次 `tool_search` 不会改变 generation，`run_conversation()` 的后续 LLM 请求仍只携带原先的 bridge schema。隐藏工具名虽可被 Executor 从全局 Registry 找到，却不是当前 LLM 请求的正式 `tools` 清单成员。是否仍能从文本里生成该工具调用取决于 Provider/模型对 tool-name 约束的实现；严格实现可能根本不会产生它。项目虽有可工作、可审计的 `tool_call` fallback，却在 prompt/description 中把它标为不应使用。

现有 MCP “search → direct call”测试直接构造 `{"name": "mcp__...", "input": ...}` 后调用 Executor，绕过了 Transport 和该轮实际发送给 LLM 的 schema，无法验证真实协议路径。

### 改造方向与完成标准

二选一并明确契约：要么搜索后把选中的工具 schema 临时加入当前 turn 后续请求（含上限、失效与 Provider 兼容测试），要么规定并引导模型始终使用 `tool_call(name, arguments)`，将其作为唯一 bridge 执行通道。后者要保留现有安全管线，并在 `tool_call` 的 schema/结果中给出参数校验错误而非依赖模型猜测。补充真实 transport/mock-provider 集成测试：初始请求只含 bridge schema，搜索后下一次请求的 tools 清单与模型实际返回的 tool name 一致；分别覆盖 strict tool-name Provider 与 `tool_call` 回退路径。

## AD-041：工具审计是同步、无轮转且静默失败的 best-effort 日志，不是可靠审计链

**状态：** 已确认，优先级中（审计可用性 / 可追溯性）。
**相关代码：** `src/personal_agent/tools/audit.py::_write_entry()`、`audit_tool_decision()`、`audit_tool_result()`；`src/personal_agent/tools/executor.py::_emit_tool_decision()`、`_finish()`。

### 当前行为与影响

Executor 会在工具决策和完成时调用审计函数，字段会脱敏并截断，这一点是正确的。但 `_write_entry()` 在当前 asyncio 事件循环线程中直接 `open(..., "a")` 和 `write()`；注释称“Non-blocking”，实际只是“不把 I/O 错误向上抛”，并不代表非阻塞 I/O。慢磁盘、网络盘或异常文件系统可暂停所有协程。日志也没有大小/时间轮转、保留策略、文件权限校验、flush/fsync 策略或健康指标。

所有审计函数以宽泛 `except Exception: pass` 吞掉目录无权限、磁盘满、序列化失败等情况。用户回合仍会继续，CLI/TUI/Gateway 和 turn report 也不会看见“本次工具缺少审计记录”的告警；因此该文件只能用于辅助排查，不能作为安全事件的完整证据链。SQLite 中的 `tool_runs` 是另一份记录，但同样没有与该 JSONL 文件组成原子提交。

### 改造方向与完成标准

明确产品级别：若仅做调试日志，应改名为 diagnostic log、后台队列写入、限额轮转并暴露 dropped/failed 计数；若要求安全审计，则使用持久队列或事务性存储、受控文件权限、可配置保留/轮转与失败告警，并为每条记录赋予稳定 turn/session/tool-use 关联键。安全关键模式下，至少要将审计失败显式写进 turn report/健康检查，是否 fail-closed 由策略决定。补充慢写入不阻塞其他 session、磁盘满产生可观测告警、轮转不丢失关联记录、脱敏与关联键正确的测试。

## AD-042：公开的 `ToolRegistry.dispatch()` 绕过 Executor，形成潜在的非审计执行旁路

**状态：** 已确认，优先级中（安全架构约束 / 扩展风险）。
**相关代码：** `src/personal_agent/tools/registry.py::ToolRegistry.dispatch()`；`src/personal_agent/tools/executor.py::execute_tool_call_result()`。

### 当前行为与影响

`ToolRegistry.dispatch(name, args)` 直接执行 `await entry.handler(**args)`，只处理未知工具与 handler 异常；它不会运行 typed Hook、hard precheck、SecurityContext 资源授权、用户确认、文件 checkpoint、重试策略、工具事件、结果截断或 audit。当前 `src/` 中没有调用该方法，主 Agent 路径正确地通过 Executor；但该公开 API 与“Executor 是唯一工具入口”的架构声明相矛盾。

后续插件、workflow 或维护代码若为方便而调用 Registry 的 dispatch，就会在不显眼的位置获得直接文件/网络/命令 handler 调用能力。单元测试不使用该 API 并不能约束未来代码；风险在扩展时才暴露，且难以从审计日志追溯。

### 改造方向与完成标准

将直接 handler 调用改为私有测试辅助方法，或删除 `dispatch()`；对外只暴露接受完整 tool call 与 SecurityContext 的 Executor API。若确有受信任的内部调用场景，应以显式、命名清楚的 capability 标识并记录结构化审计，不能让通用 Registry 提供无保护捷径。增加架构测试或静态检查：生产代码除 Executor/明确的 bootstrap 适配器外不得直接调用 `ToolEntry.handler` 或 `ToolRegistry.dispatch()`。

## AD-043：`tool_runs` 与 `turn_reports` 仅在回合结束后分开写入，崩溃和局部失败会留下不可解释的观测空洞

**状态：** 已确认，优先级中（运行可观测性 / 事件一致性）。
**相关代码：** `src/personal_agent/conversation/service.py::_record_tool_runs()`、`_record_turn_report()`、`_tool_runs_from_events()`；`src/personal_agent/db/database.py::save_tool_runs()`、`save_turn_report()`。

### 当前行为与影响

每个工具的 `tool_start`、`tool_decision`、`tool_end` 先仅保存在本回合的 EventRecorder 内存列表中。回合结束后，ConversationService 先单独提交 `turn_reports`，再单独提交由 `tool_end` 事件投影出的 `tool_runs`；两个方法各自取得 SQLite 写锁并各自 `commit`。进程在回合执行中崩溃、工具卡死、或任一步持久化失败时，数据库不会留下已开始/已授权但没有结束的工具记录；若 report 写入成功而 tool runs 失败（或反过来），同一 `turn_id` 的统计与明细也会脱节。

`_record_tool_runs()`/`_record_turn_report()` 仅记录日志并继续返回用户回复，内存中的最近队列也只在各自写入成功后更新。因此 `/tool-runs`、持久化 turn report、JSONL audit 三者可能对同一回合给出不同答案，且没有“持久化不完整”标记。

### 改造方向与完成标准

为工具生命周期设计 durable event/outbox：至少在 `tool_start`/决策时写入 pending 记录，在 `tool_end` 时更新状态；回合结束时将 report 与该 turn 的最终工具投影放入同一 SQLite transaction，或在 report 中记录明确的 persistence state。启动时扫描并标记超过阈值的 pending run 为 interrupted/unknown，而不是静默消失。对 report/tool-run 写入失败暴露结构化健康状态与 turn warning。补充“工具执行中进程终止”“只写入 report / 只写入 tool runs 失败”“重启后恢复或标记未完成 run”的回归测试。

## AD-044：SQLite 的工具完整输出与元数据未脱敏，`audit.log` 脱敏不构成持久化隐私保护

**状态：** 已修改（待回归验证）。
**相关代码：** `src/personal_agent/text_safety.py`；`src/personal_agent/tools/redact.py`；`src/personal_agent/db/database.py`；`src/personal_agent/tools/audit.py`；`src/personal_agent/conversation/service.py`；`src/personal_agent/conversation/query.py`。

### 旧版行为与影响

`tool_end` 事件携带 `full_output`、artifacts 和 `result_metadata`；Service 将其直接投影到 tool run。Database 写入前只调用 `clean_text()`/`clean_payload()`，这两个函数仅替换无法 UTF-8 编码的 surrogate，不会调用 `tools.redact.redact()`。所以读取到的文件正文、命令输出、MCP 返回、URL 中令牌、artifact 元数据或未来插件的敏感字段会原样进入 `state.db`，并可通过 `/tool-runs show` 或数据库文件被再次读取。

这与 `audit.py` 对 detail/result 摘要执行 `redact()` 的行为不同，形成危险的错误安全感；turn report 的 `report_json` 同样只做 UTF-8 清理。即使原始 `.env` 已被文件工具屏蔽，其他工具、MCP、异常信息和用户授权范围仍可能意外回显机密。

### 已落地改造

- `text_safety` 提供唯一 persistence sanitizer：`sanitize_persistence_text` / `sanitize_persistence_payload` / `sanitize_tool_artifacts` / `sanitize_tool_run_for_persistence`；字段分类为 `public` / `sensitive` / `secret` / `debug-opt-in`。
- `clean_*` 仅负责 UTF-8 清理；持久化出口必须走 `sanitize_persistence_*`。
- `save_message` / `save_tool_runs` / `save_turn_report` / `export_jsonl` / audit writer 均调用 sanitizer；`full_output` 默认截断至 8000 字符并脱敏；artifact 只保留 allowlist 摘要字段。
- ConversationService 在写入内存近期 tool runs 前先做安全投影；`/tool-runs show` 经 query 边界再次投影，避免遗留明文。
- `redact()` 补齐 Bearer、URL query secret、Cookie 头与 `token=` 赋值等形式。

### 仍未做 / 后续

- 显式 opt-in 的加密原始证据仓（受限权限、密钥管理、TTL、访问审计）尚未实现；默认路径不再把原文塞进 `state.db`。
- 既有数据库的一次性扫描/迁移告警可在 doctor 或独立脚本中继续补齐。

### 回归测试

- `tests/test_persistence_sanitizer.py`
- `tests/test_database.py::test_persistence_redacts_tool_outputs_metadata_reports_and_exports`

## AD-045：测试套件缺少仓库级 CI、静态检查与覆盖率门禁

**状态：** 已确认，优先级中（回归防护 / 工程交付）。
**相关位置：** `pyproject.toml` 的 dev dependency；仓库根目录自动化配置。

### 当前行为与影响

项目已有大量 `pytest` / `pytest-asyncio` 单元和局部集成测试，且 `tests/conftest.py` 提供临时 SQLite、测试 Settings 与 audit 文件隔离；这是良好基础。但 `pyproject.toml` 只声明测试依赖，没有 pytest 的 asyncio/strict 配置、coverage 阈值、ruff/format/type-check 配置；仓库内也未发现 GitHub Actions 或等价 CI workflow。换言之，测试是否运行、运行哪个集合、是否允许覆盖率下降、格式/类型错误是否阻断合并，都依赖开发者手工执行。

对 Agent 而言，最容易回归的正是安全和协议边界：工具绕过 Executor、权限确认、持久化脱敏、跨 Provider tool schema、取消与并发。这些即使已有局部测试，也无法在没有统一命令和持续门禁的情况下保证每次提交都被执行。

### 改造方向与完成标准

在 `pyproject.toml` 固化测试与质量命令（至少 `pytest -q`、asyncio mode、lint/format、基础 type-check），并以 CI 在 Python 3.12 上执行；把网络/真实凭据测试显式标记为 integration/e2e 并默认隔离。对 `security`、`conversation`、`tools`、`persistence` 设置渐进式覆盖率目标，优先加入 AD-036～AD-044 的回归测试。CI 应上传失败时的安全脱敏日志和测试报告，但绝不上传 `state.db`、`.env` 或完整工具输出。

## AD-046：工具参数解析失败与合法空对象均表示为 `{}`，导致零参数工具被 Agent Loop 错误拦截

**状态：** 已确认，优先级中（工具协议正确性）。
**相关代码：** `src/personal_agent/plugins/builtin/llm/builtin/chat_completions.py::parse_stream()`；`plugins/builtin/llm/builtin/anthropic.py::parse_stream()`；`src/personal_agent/agent/loop.py` 的 invalid tool retry。

### 当前行为与影响

两个 streaming Transport 在 tool arguments JSON 解析失败时只记录 warning，然后把 `input` 设为 `{}`。Agent Loop 随后用 `if not tc.get("input") and tc.get("name")` 判定“参数 JSON 非法”；因此它同样把合法的空对象当成错误。项目内已有 `process_list`、`process_clear` 等 schema 的 `required: []` 工具，模型按协议调用 `{"name": "process_list", "input": {}}` 时不会进入 Executor，而会被要求“请用有效 JSON 重试”。

系统由此丢失了两个不同语义：`arguments` 解析失败、工具调用本身没有参数（合法或不合法要由 schema 决定）。除了零参数工具不可用外，模型也无法得到具体字段/JSON 错误；最多重试到上限后，后续行为变得不可预测。

### 改造方向与完成标准

在 `NormalizedResponse` 或 tool-call 数据结构保留显式 `arguments_parse_error` / `raw_arguments`，而不是用 `{}` 作为错误哨兵。Agent Loop 只在该标记为真时执行 JSON 修复重试；合法空对象必须交给 schema validation。为每个 ToolEntry 在 Executor 前运行 JSON Schema（至少 required、type、additionalProperties 策略）校验，并把可读错误作为 tool result 返回。补充 OpenAI/Anthropic 流式“合法 `{}` 零参数工具可以执行”“损坏 JSON 被重试且不会执行”“缺失必填字段由 schema 拒绝”的回归测试。

## AD-047：SSE 已产生部分事件后仍自动重试同一 LLM 请求，可能拼接重复响应

**状态：** 已确认，优先级高（流式输出正确性 / 成本）。
**相关代码：** `src/personal_agent/llm/client.py::_call_with_retry()`；各 Transport 的 `parse_stream()` 与 delta callback。

### 当前行为与影响

`_call_with_retry()` 在 `async for response.aiter_lines()` 中逐条 yield SSE JSON；若流已经产生若干事件后发生 `httpx.TimeoutException`、`ConnectError` 或 `RemoteProtocolError`，外层 catch 仍会按连接错误重新 POST 同一个请求。它不记录本次 attempt 是否已向上游 yield 数据。

上层 Transport 在收到事件时已经累计 text/thinking/tool-call 片段，并在有 `on_delta` 时立即发给 TUI；重试后的完整或部分第二份响应会继续追加到同一解析状态。结果可能是用户看见重复 token、最终 text 拼接两次、tool argument JSON 拼坏，或模型第二次生成不同工具调用；同时消耗额外请求与 token。即使工具尚未执行，Agent 对已展示内容与最终持久化内容也会失去一致性。

### 改造方向与完成标准

只允许在尚未接收任何响应事件前重试连接/5xx；一旦开始消费流，停止透明重试并将明确的 stream-interrupted 错误交给 Agent Loop，由上层以新的、可审计的回合策略决定是否重试。另一种方案是完全缓冲一个尝试成功后才发布 delta，但这会放弃低延迟流式体验。为 client 返回 `attempt_started/bytes_or_events_seen` 元数据，报告和 UI 应标记中断。补充“首个 SSE 后断开不产生第二个 POST/不重复 delta”“首事件前连接失败可重试”“工具 JSON 中途断流不会被拼接并执行”的测试。
