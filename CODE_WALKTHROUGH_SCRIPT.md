# Code Walkthrough Script (3 Minutes)

**准备**: 提前打开以下文件，方便切换展示
- participant_node.py
- coordinator.py
- client.py

---

## 开场 (0:00 - 0:15)

**展示**: VSCode文件树或 `ls` 命令输出

**台词**:
```
"Let me give you a quick walkthrough of the code structure.
We have five main Python files: participant_node, participant_server,
coordinator, coordinator_server, and client.
The core logic is in participant_node and coordinator."
```

---

## Part 1: participant_node.py - Raft Layer (0:15 - 1:15)

### 1.1 类定义和状态 (0:15 - 0:30)

**展示**: `participant_node.py` 第 **19-145 行**

**关键代码位置**:
- 第 19-23 行: `NodeState` 枚举 (FOLLOWER, CANDIDATE, LEADER)
- 第 26-31 行: `TxState` 枚举 (2PC状态)
- 第 34-49 行: `LogEntry` 类定义
- 第 79-145 行: `ParticipantNode.__init__()` 初始化

**台词**:
```
"In participant_node.py, we implement both Raft consensus and the 2PC participant.

Starting at line 19, we define NodeState enum with three states:
Follower, Candidate, and Leader.

Line 26 defines TxState for 2PC transaction states.

Line 34 defines LogEntry class that holds term, index, and command.

And starting at line 79, the ParticipantNode class initialization.
Key Raft variables include current_term at line 102, voted_for at line 103,
the log entries at line 104, and commit_index at line 107."
```

---

### 1.2 Leader Election (0:30 - 0:50)

**展示**: `participant_node.py` 第 **539-618 行**

**关键代码位置**:
- 第 539-561 行: `start_election()` 方法
- 第 563-599 行: `send_request_vote()` 方法
- 第 601-618 行: `become_leader()` 方法

**台词**:
```
"The election logic starts at line 539, the start_election function.

Line 542: the node becomes a CANDIDATE.
Line 543: it increments its term.
Line 544: it votes for itself.

Then at line 556-561, it sends RequestVote RPCs to all peers.

If it receives majority votes, line 601, the become_leader function
transitions the node to LEADER state at line 606.
You can see the announcement at line 616."
```

---

### 1.3 Log Replication (0:50 - 1:15)

**展示**: `participant_node.py` 第 **483-535 行** 和 **213-260 行**

**关键代码位置**:
- 第 483-535 行: `append_entries()` RPC handler
- 第 504-511 行: Log consistency check
- 第 514-526 行: Append new entries
- 第 528-533 行: Update commit index
- 第 213-260 行: `apply_to_state_machine()` 应用日志

**台词**:
```
"append_entries RPC handler is at line 483.

Line 488: it checks if this is a heartbeat or has actual entries.

Line 504-511: the log consistency check.
If prev_log_index doesn't match, return false.

Line 514-526: append the new entries to the log.

Line 528-533: update commit index based on leader's commit.

When entries are committed, line 213, apply_to_state_machine
applies them to the account balance.
Line 227 handles PREPARE, line 239 handles COMMIT, line 252 handles ABORT."
```

---

## Part 2: participant_node.py - 2PC Layer (1:15 - 1:45)

**展示**: `participant_node.py` 第 **264-392 行**

**关键代码位置**:
- 第 264-345 行: `prepare()` 方法
- 第 287-303 行: 验证操作（如余额检查）
- 第 315-326 行: 创建PREPARE日志条目
- 第 332-345 行: 等待majority确认
- 第 347-392 行: `commit()` 方法

**台词**:
```
"The 2PC layer starts at line 264, the prepare function.

Line 279: Only the leader can handle 2PC requests.

Line 287-303: Validation logic.
For a debit operation, line 291-297, we check if balance is sufficient.
If not, return VOTE_ABORT.

Line 305: Validation passed.

Line 315-324: Create a PREPARE log entry and append to Raft log.

Line 332: send_heartbeats replicates this to followers.

Line 336: wait for majority confirmation using _wait_for_commit.

Line 339: If majority confirmed, return VOTE_COMMIT.
Otherwise, line 344, return VOTE_ABORT.

The commit function at line 347 is similar.
Line 365-372: Create COMMIT log entry.
Line 380: Replicate to followers.
Line 384: Wait for majority before confirming."
```

---

## Part 3: coordinator.py (1:45 - 2:30)

### 3.1 execute_transaction (1:45 - 2:05)

**展示**: `coordinator.py` 第 **286-441 行**

**关键代码位置**:
- 第 286-309 行: 方法定义和初始化
- 第 312-329 行: 查找各组leader
- 第 331-390 行: Phase 1 PREPARE
- 第 392-441 行: Phase 2 COMMIT/ABORT

**台词**:
```
"The coordinator's execute_transaction starts at line 286.

Line 295: generate a unique transaction ID.

Line 302-309: Initialize transaction log with PENDING status.

Line 312-329: Find the leader for each participant group.

Line 332: Phase 1 PREPARE begins.

Line 339-382: Send PREPARE to all groups and collect votes.
Line 348: Call proxy.prepare() on the group leader.
Line 369: If vote is COMMIT, log it. Otherwise at line 372, VOTE_ABORT.

Line 385: Check if all voted COMMIT.

Line 393: If yes, Phase 2 COMMIT at line 394.
Line 436: Call _commit_transaction.

Line 438: Otherwise, ABORT at line 439.
Line 441: Call _abort_transaction."
```

---

### 3.2 Crash Recovery (2:05 - 2:30)

**展示**: `coordinator.py` 第 **139-247 行** 和 **94-105 行**

**关键代码位置**:
- 第 94-105 行: `load_tx_log()` 加载日志
- 第 139-247 行: `recover_incomplete_transactions()` 恢复逻辑
- 第 159-193 行: 处理未完成的COMMIT
- 第 197-220 行: 处理未完成的ABORT
- 第 443-478 行: `_commit_transaction()` 实际执行

**台词**:
```
"Crash recovery starts at line 94, load_tx_log.
This loads the transaction log from disk.

Line 139: recover_incomplete_transactions runs on coordinator startup.

Line 148: Loop through all transactions in the log.

Line 159: Check if decision was COMMIT but status is not COMMITTED yet.
This means coordinator crashed after making decision but before completing.

Line 161: Print recovery message.

Line 168-177: Find current group leaders.

Line 180-188: Resend COMMIT to all participants.

Line 191-193: Mark as committed and save.

Line 443: The actual _commit_transaction method.
CRITICAL: Line 448, set decision to COMMIT and save to disk FIRST.
Line 449: save_tx_log persists the decision.

Then line 452-467: Send COMMIT to all participants.

This ensures atomicity even through coordinator crashes."
```

---

## Part 4: client.py (2:30 - 2:50)

**展示**: `client.py` 第 **155-186 行** 和 **664-726 行**

**关键代码位置**:
- 第 30-53 行: `Lab3Client` 类定义和配置
- 第 155-173 行: `execute_transfer()` 方法
- 第 175-185 行: `execute_bonus()` 方法
- 第 664-726 行: `run_all_scenarios()` 主菜单

**台词**:
```
"The client provides a menu interface for testing scenarios.

Line 155: execute_transfer function.
Line 158-166: Create operations dictionary with debit for source
and credit for destination.

Line 170-172: Call coordinator's execute_transaction via RPC.

Line 664: run_all_scenarios provides the main menu.
Line 677-686: Lists all test scenarios including
normal operations, insufficient funds, and crash recovery tests.

Line 189-245: scenario_1a_t1_first is an example test.
Line 200-202: Set initial balances.
Line 210-213: Execute T1 transfer.
Line 226-229: Execute T2 bonus transaction."
```

---

## 结尾 (2:50 - 3:00)

**展示**: 运行中的系统终端或架构图

**台词**:
```
"That's a quick overview of the code structure.

The key insight is how Raft consensus at the participant level
combines with 2PC at the coordinator level
to provide both fault tolerance and atomicity
for distributed transactions.

Each participant group runs Raft for replication,
and the coordinator runs 2PC across the groups.

Thank you!"
```

---

## 附录: 关键文件和行数速查表

| 功能 | 文件 | 行数 | 说明 |
|------|------|------|------|
| NodeState定义 | participant_node.py | 19-23 | Raft节点状态枚举 |
| ParticipantNode初始化 | participant_node.py | 79-145 | 节点初始化 |
| start_election | participant_node.py | 539-561 | 发起选举 |
| become_leader | participant_node.py | 601-618 | 成为Leader |
| append_entries | participant_node.py | 483-535 | 日志复制RPC |
| apply_to_state_machine | participant_node.py | 213-260 | 应用日志到状态机 |
| prepare (2PC) | participant_node.py | 264-345 | 2PC准备阶段 |
| commit (2PC) | participant_node.py | 347-392 | 2PC提交阶段 |
| execute_transaction | coordinator.py | 286-441 | 执行2PC事务 |
| Phase 1 PREPARE | coordinator.py | 331-390 | 2PC第一阶段 |
| Phase 2 COMMIT | coordinator.py | 392-441 | 2PC第二阶段 |
| _commit_transaction | coordinator.py | 443-478 | 提交事务实现 |
| load_tx_log | coordinator.py | 94-105 | 加载事务日志 |
| recover_incomplete_transactions | coordinator.py | 139-247 | 崩溃恢复 |
| execute_transfer | client.py | 155-173 | 转账操作 |
| run_all_scenarios | client.py | 664-726 | 测试主菜单 |

---

## 时间分配总结

- **0:00-0:15**: 开场介绍文件结构
- **0:15-0:30**: Raft状态定义
- **0:30-0:50**: Raft选举机制
- **0:50-1:15**: Raft日志复制
- **1:15-1:45**: 2PC准备和提交
- **1:45-2:05**: Coordinator事务执行
- **2:05-2:30**: 崩溃恢复机制
- **2:30-2:50**: 客户端测试接口
- **2:50-3:00**: 总结

**总计**: 3分钟
