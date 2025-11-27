# CISC 6935 Lab 3: Two-Phase Commit (2PC) with Raft Consensus

A distributed transaction system implementing 2PC protocol with Raft consensus for high availability. This system manages two accounts (A and B) across 11 nodes with fault tolerance.

## Architecture

```
                        ┌─────────────────────┐
                        │ Coordinator (node1) │
                        │   10.128.0.2        │
                        │   2PC Protocol      │
                        └──────────┬──────────┘
                                   │
               ┌───────────────────┴───────────────────┐
               │                                       │
               ▼                                       ▼
    ┌─────────────────────┐             ┌─────────────────────┐
    │  Account A Group    │             │  Account B Group    │
    │  (Raft Cluster)     │             │  (Raft Cluster)     │
    │  5-node Raft        │             │  5-node Raft        │
    ├─────────────────────┤             ├─────────────────────┤
    │ Node 0: 10.128.0.5  │             │ Node 6: 10.128.0.10 │
    │ Node 2: 10.128.0.3  │             │ Node 7: 10.128.0.11 │
    │ Node 3: 10.128.0.4  │             │ Node 8: 10.128.0.24 │
    │ Node 4: 10.128.0.6  │             │ Node 9: 10.128.0.25 │
    │ Node 5: 10.128.0.8  │             │ Node 10: 10.128.0.26│
    └─────────────────────┘             └─────────────────────┘
```

**Total: 11 nodes = 1 Coordinator + 5 Account A + 5 Account B**

### Why Raft Election is Critical

Raft leader election is the **prerequisite for high availability**:
- Without dynamic election, if a statically configured Leader fails, the entire cluster stops
- Election logs prove that Leader identity is obtained through **distributed consensus**, not hardcoded
- In scenario 1.c.iii, election logs prove the system can recover automatically after Leader crash

**Note**: The Leader node numbers shown in logs (e.g., Node 2) are the result of runtime elections, not fixed configuration. Each time the cluster starts, a different Leader may be elected.

## Two-Layer Architecture

### Layer 1: 2PC Protocol (Coordinator ↔ Participant Leaders)
- PREPARE phase: Coordinator sends PREPARE to all participant group leaders
- VOTE phase: Each participant validates and votes COMMIT or ABORT
- COMMIT/ABORT phase: Coordinator makes final decision based on votes

### Layer 2: Raft Consensus (Within Each Participant Group)
- Before returning VOTE_COMMIT, leader must replicate PREPARE to Raft majority
- Before applying COMMIT, leader must replicate COMMIT to Raft majority
- This ensures durability even if nodes crash

```
Coordinator                    Participant Leader              Raft Followers
    │                               │                              │
    │──── PREPARE ─────────────────>│                              │
    │                               │──── AppendEntries ──────────>│
    │                               │<─── Success (majority) ──────│
    │<─── VOTE_COMMIT ──────────────│                              │
    │                               │                              │
    │──── COMMIT ──────────────────>│                              │
    │                               │──── AppendEntries ──────────>│
    │                               │<─── Success (majority) ──────│
    │<─── ACK ──────────────────────│                              │
```

## Files

| File | Description | Run on |
|------|-------------|--------|
| `coordinator_server.py` | 2PC Coordinator | node1 |
| `coordinator.py` | Coordinator logic | (imported) |
| `participant_server.py` | Raft participant server | nodes 0,2-10 |
| `participant_node.py` | Participant logic + Raft | (imported) |
| `client.py` | Test client for all scenarios | any machine |
| `cleanup.sh` | Remove all state files | all nodes |

## Quick Start

### 1. Clean Old State (On ALL Nodes)

```bash
./cleanup.sh
# OR manually:
rm -f raft_state_*.json raft_log_*.log account_*.dat coordinator_tx_log.json
```

### 2. Start Coordinator (Node 1)

```bash
# SSH to node1 (10.128.0.2)
python3 coordinator_server.py
```

### 3. Start Account A Participants (Nodes 0, 2-5)

```bash
# SSH to each node and run:
python3 participant_server.py 0   # on node0
python3 participant_server.py 2   # on node2
python3 participant_server.py 3   # on node3
python3 participant_server.py 4   # on node4
python3 participant_server.py 5   # on node5
```

### 4. Start Account B Participants (Nodes 6-10)

```bash
python3 participant_server.py 6   # on node6
python3 participant_server.py 7   # on node7
python3 participant_server.py 8   # on node8
python3 participant_server.py 9   # on node9
python3 participant_server.py 10  # on node10
```

### 5. Run Tests (From any machine that can reach the cluster)

```bash
python3 client.py
```

## Test Scenarios

### Scenario 1.a (15%): Normal Operation
- Initial: A=200, B=300
- T1: Transfer $100 from A to B
- T2: Add 20% of A's balance to both accounts
- Both transactions should succeed

### Scenario 1.b (20%): Insufficient Funds
- Initial: A=90, B=50
- T1 will fail if executed first (A < 100)
- Order affects outcome

### Scenario 1.c.i (20%): Participant Crash Before Voting
- Participant crashes before responding to PREPARE
- Coordinator times out, transaction ABORTs

### Scenario 1.c.ii (20%): Participant Crash After Voting
- Participant crashes after voting COMMIT
- Coordinator commits, crashed node recovers

### Scenario 1.c.iii (10%): Leader Crash and Re-election
- Leader crashes during transaction
- Raft elects new leader, service continues

## Expected Log Output Examples

### 0. Leader Election Logs (Must Show at Startup)

**Account A Group Election (5 nodes: 0, 2-5):**
```
[A-Node 2] [Raft Election] Starting election, Term=1
[A-Node 2] [Raft Election] Voted for self, current votes: 1/5

[A-Node 0] [Raft Election] Received vote request from Node 2 (Term 1)
[A-Node 0] [Raft Election] Voted for Node 2 (Term 1)

[A-Node 3] [Raft Election] Received vote request from Node 2 (Term 1)
[A-Node 3] [Raft Election] Voted for Node 2 (Term 1)

[A-Node 2] [Raft Election] Received vote from Node 0, current votes: 2/5 (need 3)
[A-Node 2] [Raft Election] Received vote from Node 3, current votes: 3/5 (need 3)

============================================================
[A-Node 2] [Raft Election] Received 3/5 votes
[A-Node 2] [Raft Election] *** Elected as LEADER (Term 1) ***
============================================================
```

**Account B Group Election (5 nodes: 6-10):**
```
[B-Node 7] [Raft Election] Starting election, Term=1
[B-Node 7] [Raft Election] Voted for self, current votes: 1/5
[B-Node 7] [Raft Election] Received vote from Node 6, current votes: 2/5 (need 3)
[B-Node 7] [Raft Election] Received vote from Node 8, current votes: 3/5 (need 3)

============================================================
[B-Node 7] [Raft Election] Received 3/5 votes
[B-Node 7] [Raft Election] *** Elected as LEADER (Term 1) ***
============================================================
```

---

### Scenario 1.a: Normal Operation (A=200, B=300)

#### 1.a.1: T1 First then T2 (Transfer first, then Bonus)

**Initial: A=200, B=300**

**T1: Transfer $100 from A to B**

Coordinator Log:
```
======================================================================
[Coordinator] Starting Transaction t1_abc
[Coordinator] Operations: {'A': {'type': 'debit', 'amount': 100}, 'B': {'type': 'credit', 'amount': 100}}
======================================================================

[Coordinator] ========== PHASE 1: PREPARE ==========
[Coordinator] Group A leader: Node 2
[Coordinator] Group B leader: Node 7
[Coordinator] Sending PREPARE to Group A (Node 2)
[Coordinator] Sending PREPARE to Group B (Node 7)
[Coordinator] Group A voted: VOTE_COMMIT
[Coordinator] Group B voted: VOTE_COMMIT

[Coordinator] ========== PHASE 2: COMMIT ==========
[Coordinator] All participants voted COMMIT -> Committing
[Coordinator] Sending COMMIT to Group A (Node 2)
[Coordinator] Group A COMMIT acknowledged. Balance: 100
[Coordinator] Sending COMMIT to Group B (Node 7)
[Coordinator] Group B COMMIT acknowledged. Balance: 400

[Coordinator] Transaction t1_abc COMMITTED
```

Account A Leader Log:
```
============================================================
[A-Node 2] [2PC Layer] Received PREPARE message
[A-Node 2] TX: t1_abc
[A-Node 2] Operation: {'type': 'debit', 'amount': 100}
============================================================
[A-Node 2] [2PC Layer] Validation passed. Current balance: 200, New balance: 100

[A-Node 2] [Raft Layer] PREPARE added to Raft Log (index=0)
[A-Node 2] [Raft Layer] Replicating PREPARE to Raft Follower nodes...
[A-Node 2] [Raft Layer] Waiting for majority confirmation (need 3 nodes)...
[A-Node 2] [Raft Layer] Majority confirmed, PREPARE persisted
[A-Node 2] [2PC Layer] Returning VOTE_COMMIT to coordinator

============================================================
[A-Node 2] [2PC Layer] Received COMMIT message
[A-Node 2] TX: t1_abc
============================================================
[A-Node 2] [Raft Layer] COMMIT added to Raft Log (index=1)
[A-Node 2] [Raft Leader] Applying committed log: commit, tx=t1_abc
[A-Node 2] [State Machine] TX t1_abc COMMITTED: balance 200 -> 100
```

Account A Follower Log:
```
[A-Node 3] AppendEntries from leader 2, entries=1
[A-Node 3] Appended 1 entries
[A-Node 3] [Raft Follower] Applying committed log: prepare, tx=t1_abc
[A-Node 3] [Raft Follower] TX t1_abc state -> PREPARED (expected balance: 100)

[A-Node 3] AppendEntries from leader 2, entries=1
[A-Node 3] [Raft Follower] Applying committed log: commit, tx=t1_abc
[A-Node 3] [State Machine] TX t1_abc COMMITTED: balance 200 -> 100
```

**After T1: A=100, B=400**

**T2: Add 20% Bonus (20% of 100 = 20)**

Coordinator Log:
```
======================================================================
[Coordinator] Starting Transaction t2_def
[Coordinator] Operations: {'A': {'type': 'credit', 'amount': 20.0}, 'B': {'type': 'credit', 'amount': 20.0}}
======================================================================

[Coordinator] ========== PHASE 1: PREPARE ==========
[Coordinator] Group A voted: VOTE_COMMIT
[Coordinator] Group B voted: VOTE_COMMIT

[Coordinator] ========== PHASE 2: COMMIT ==========
[Coordinator] Transaction t2_def COMMITTED
```

**Final Result: A=120, B=420**

---

#### 1.a.2: T2 First then T1 (Bonus first, then Transfer)

**Initial: A=200, B=300**

**T2: Add 20% Bonus (20% of 200 = 40)**

Coordinator Log:
```
======================================================================
[Coordinator] Starting Transaction t2_ghi
[Coordinator] Operations: {'A': {'type': 'credit', 'amount': 40.0}, 'B': {'type': 'credit', 'amount': 40.0}}
======================================================================

[Coordinator] ========== PHASE 1: PREPARE ==========
[Coordinator] Group A voted: VOTE_COMMIT
[Coordinator] Group B voted: VOTE_COMMIT

[Coordinator] ========== PHASE 2: COMMIT ==========
[Coordinator] Transaction t2_ghi COMMITTED
```

Account A Leader Log:
```
============================================================
[A-Node 2] [2PC Layer] Received PREPARE message
[A-Node 2] TX: t2_ghi
[A-Node 2] Operation: {'type': 'credit', 'amount': 40.0}
============================================================
[A-Node 2] [2PC Layer] Validation passed. Current balance: 200, New balance: 240

[A-Node 2] [Raft Layer] PREPARE added to Raft Log (index=0)
[A-Node 2] [Raft Layer] Waiting for majority confirmation (need 3 nodes)...
[A-Node 2] [Raft Layer] Majority confirmed, PREPARE persisted
[A-Node 2] [2PC Layer] Returning VOTE_COMMIT to coordinator

[A-Node 2] [State Machine] TX t2_ghi COMMITTED: balance 200 -> 240
```

**After T2: A=240, B=340**

**T1: Transfer $100 from A to B**

Coordinator Log:
```
======================================================================
[Coordinator] Starting Transaction t1_jkl
[Coordinator] Operations: {'A': {'type': 'debit', 'amount': 100}, 'B': {'type': 'credit', 'amount': 100}}
======================================================================

[Coordinator] ========== PHASE 1: PREPARE ==========
[Coordinator] Group A voted: VOTE_COMMIT
[Coordinator] Group B voted: VOTE_COMMIT

[Coordinator] ========== PHASE 2: COMMIT ==========
[Coordinator] Transaction t1_jkl COMMITTED
```

Account A Leader Log:
```
[A-Node 2] [2PC Layer] Validation passed. Current balance: 240, New balance: 140
[A-Node 2] [State Machine] TX t1_jkl COMMITTED: balance 240 -> 140
```

**Final Result: A=140, B=440**

---

### Scenario 1.b: Insufficient Funds (A=90, B=50)

#### 1.b.1: T1 First then T2 (T1 ABORTS due to insufficient funds)

**Initial: A=90, B=50**

**T1: Transfer $100 from A to B -> ABORT**

Coordinator Log:
```
======================================================================
[Coordinator] Starting Transaction t1_fail
[Coordinator] Operations: {'A': {'type': 'debit', 'amount': 100}, 'B': {'type': 'credit', 'amount': 100}}
======================================================================

[Coordinator] ========== PHASE 1: PREPARE ==========
[Coordinator] Sending PREPARE to Group A (Node 2)
[Coordinator] Sending PREPARE to Group B (Node 7)
[Coordinator] Group A voted: VOTE_ABORT (Insufficient balance: 90 < 100)
[Coordinator] Group B voted: VOTE_COMMIT

[Coordinator] ========== PHASE 2: ABORT ==========
[Coordinator] Not all voted COMMIT -> Aborting
[Coordinator] Sending ABORT to Group A (Node 2)
[Coordinator] Sending ABORT to Group B (Node 7)

[Coordinator] Transaction t1_fail ABORTED
[Coordinator] Reason: A: Insufficient balance: 90 < 100
```

Account A Leader Log:
```
============================================================
[A-Node 2] [2PC Layer] Received PREPARE message
[A-Node 2] TX: t1_fail
[A-Node 2] Operation: {'type': 'debit', 'amount': 100}
============================================================
[A-Node 2] [2PC Layer] Validation FAILED!
[A-Node 2] [2PC Layer] Insufficient balance: current 90 < required 100
[A-Node 2] [2PC Layer] Returning VOTE_ABORT to coordinator

============================================================
[A-Node 2] [2PC Layer] Received ABORT message
[A-Node 2] TX: t1_fail
============================================================
[A-Node 2] [2PC Layer] Transaction ABORTED. Balance unchanged: 90
```

**After T1: A=90, B=50 (unchanged)**

**T2: Add 20% Bonus (20% of 90 = 18) -> SUCCESS**

Coordinator Log:
```
======================================================================
[Coordinator] Starting Transaction t2_ok
[Coordinator] Operations: {'A': {'type': 'credit', 'amount': 18.0}, 'B': {'type': 'credit', 'amount': 18.0}}
======================================================================

[Coordinator] ========== PHASE 1: PREPARE ==========
[Coordinator] Group A voted: VOTE_COMMIT
[Coordinator] Group B voted: VOTE_COMMIT

[Coordinator] ========== PHASE 2: COMMIT ==========
[Coordinator] Transaction t2_ok COMMITTED
```

**Final Result: A=108, B=68**

---

#### 1.b.2: T2 First then T1 (Both succeed after bonus)

**Initial: A=90, B=50**

**T2: Add 20% Bonus (20% of 90 = 18) -> SUCCESS**

Coordinator Log:
```
======================================================================
[Coordinator] Starting Transaction t2_first
[Coordinator] Operations: {'A': {'type': 'credit', 'amount': 18.0}, 'B': {'type': 'credit', 'amount': 18.0}}
======================================================================

[Coordinator] ========== PHASE 1: PREPARE ==========
[Coordinator] Group A voted: VOTE_COMMIT
[Coordinator] Group B voted: VOTE_COMMIT

[Coordinator] ========== PHASE 2: COMMIT ==========
[Coordinator] Transaction t2_first COMMITTED
```

**After T2: A=108, B=68**

**T1: Transfer $100 from A to B -> SUCCESS (now A=108 >= 100)**

Coordinator Log:
```
======================================================================
[Coordinator] Starting Transaction t1_now_ok
[Coordinator] Operations: {'A': {'type': 'debit', 'amount': 100}, 'B': {'type': 'credit', 'amount': 100}}
======================================================================

[Coordinator] ========== PHASE 1: PREPARE ==========
[Coordinator] Group A voted: VOTE_COMMIT
[Coordinator] Group B voted: VOTE_COMMIT

[Coordinator] ========== PHASE 2: COMMIT ==========
[Coordinator] Transaction t1_now_ok COMMITTED
```

Account A Leader Log:
```
[A-Node 2] [2PC Layer] Validation passed. Current balance: 108, New balance: 8
[A-Node 2] [State Machine] TX t1_now_ok COMMITTED: balance 108 -> 8
```

**Final Result: A=8, B=168**

---

### Scenario 1.c.i: Participant Crash Before Voting (Timeout ABORT)

**Coordinator Log:**
```
[Coordinator] ========== PHASE 1: PREPARE ==========
[Coordinator] Sending PREPARE to Group A (Node 2)
[Coordinator] Sending PREPARE to Group B (Node 7)
[Coordinator] Group A: RPC timeout -> VOTE_ABORT
[Coordinator] Group B voted: VOTE_COMMIT

[Coordinator] ========== PHASE 2: ABORT ==========
[Coordinator] Sending ABORT to Group B (Node 7)

[Coordinator] Transaction ABORTED
[Coordinator] Reason: A: RPC timeout
```

**Account B Leader Log:**
```
============================================================
[B-Node 7] [2PC Layer] Received ABORT message
[B-Node 7] TX: crashed_tx
============================================================
[B-Node 7] [Raft Layer] ABORT added to Raft Log (index=1)
[B-Node 7] [2PC Layer] Transaction ABORTED. Balance unchanged: 300
```

---

### Scenario 1.c.ii: Participant Crash After Voting (Recovery)

**How it works:**
1. Coordinator sends PREPARE, receives VOTE_COMMIT from all participants
2. Coordinator pauses for 10 seconds (crash demo window)
3. During pause, user crashes the **Participant Leader** (not Coordinator!)
4. Coordinator completes COMMIT (it already has all votes)
5. Crashed node recovers via Raft replication when restarted

**Step 1: Coordinator receives all votes and pauses:**
```
[Coordinator] ========== PHASE 1: PREPARE ==========
[Coordinator] Sending PREPARE to Group A (Node 2)
[Coordinator] Sending PREPARE to Group B (Node 7)
[Coordinator] Group A voted: VOTE_COMMIT
[Coordinator] Group B voted: VOTE_COMMIT

[Coordinator] ========== PHASE 2: COMMIT ==========
[Coordinator] All participants voted COMMIT -> Committing

!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
!!! PAUSE FOR 1.c.ii CRASH DEMO (10 seconds) !!!
!!! Go to PARTICIPANT LEADER terminal and press Ctrl+C NOW !!!
!!! Participants are in PREPARED state !!!
!!! After crash, Coordinator will still complete COMMIT !!!
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

[Coordinator] Countdown: 10 seconds remaining...
# --- User switches to Group A Leader terminal and presses Ctrl+C ---
```

**Step 2: Coordinator continues (Group A crashed):**
```
[Coordinator] Crash window closed, continuing with COMMIT...
[Coordinator] Sending COMMIT to Group A (Node 2)
[Coordinator] Group A: Connection failed (node crashed)
[Coordinator] Sending COMMIT to Group B (Node 7)
[Coordinator] Group B COMMIT acknowledged. Balance: 400

[Coordinator] Transaction 4ef44609 COMMITTED ✓
```

**Step 3: After restarting crashed node:**
```
# Restart: python3 participant_server.py 2

[A-Node 2] Initialized with balance=0.0
[A-Node 2] Loaded state: term=1, log_len=1
[A-Node 2] Started

# Node syncs with other Raft nodes and receives COMMIT entry
[A-Node 2] AppendEntries from leader 3, entries=1
[A-Node 2] [Raft Follower] Applying committed log: commit, tx=4ef44609
[A-Node 2] [State Machine] TX 4ef44609 COMMITTED: balance 200 -> 100
```

**Final Result:** All nodes consistent - A=100, B=400

---

### Scenario 1.c.iii: Coordinator Crash and Recovery (6935 Only)

**Step 1: Coordinator receives all votes, then crash window:**
```
[Coordinator] ========== PHASE 1: PREPARE ==========
[Coordinator] Sending PREPARE to Group A (Node 2)
[Coordinator] Sending PREPARE to Group B (Node 7)
[Coordinator] Group A voted: VOTE_COMMIT
[Coordinator] Group B voted: VOTE_COMMIT

[Coordinator] ========== PHASE 2: COMMIT ==========
[Coordinator] All participants voted COMMIT -> Committing

!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
!!! PAUSE FOR 1.c.iii CRASH DEMO (10 seconds) !!!
!!! Press Ctrl+C NOW to simulate Coordinator crash !!!
!!! Participants are in PREPARED state, waiting for COMMIT !!!
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

[Coordinator] Countdown: 10 seconds remaining...
[Coordinator] Countdown: 9 seconds remaining...
# --- User presses Ctrl+C here ---
```

**Step 2: Participants are stuck in PREPARED state:**
```
[A-Node 2] TX tx_abc state -> PREPARED (expected balance: 100)
# Node is waiting for COMMIT message that never comes...
```

**Step 3: Coordinator restarts and recovers:**
```
============================================================
Starting 2PC Coordinator (Node 1)
============================================================
[Coordinator] Loaded 1 transactions from log

[Coordinator] ========== CRASH RECOVERY ==========
[Coordinator] Checking for incomplete transactions...
[Coordinator] TX tx_abc: status=committing, decision=COMMIT

[Coordinator] [Recovery] Found incomplete COMMIT for TX tx_abc
[Coordinator] [Recovery] Resuming Phase 2: COMMIT...
[Coordinator] [Recovery] Group A leader: Node 2
[Coordinator] [Recovery] Group B leader: Node 7
[Coordinator] [Recovery] Sending COMMIT to Group A (Node 2)
[Coordinator] [Recovery] Group A COMMIT result: {'success': True, 'balance': 100}
[Coordinator] [Recovery] Sending COMMIT to Group B (Node 7)
[Coordinator] [Recovery] Group B COMMIT result: {'success': True, 'balance': 400}
[Coordinator] [Recovery] TX tx_abc COMMITTED successfully

[Coordinator] [Recovery] Recovered 1 incomplete transaction(s)
[Coordinator] ========== RECOVERY COMPLETE ==========
```

**Step 4: Participants receive delayed COMMIT:**
```
============================================================
[A-Node 2] [2PC Layer] Received COMMIT message
[A-Node 2] TX: tx_abc
============================================================
[A-Node 2] [Raft Layer] COMMIT added to Raft Log (index=1)
[A-Node 2] [Raft Leader] Applying committed log: commit, tx=tx_abc
[A-Node 2] [State Machine] TX tx_abc COMMITTED: balance 200 -> 100
```

**Final Result:** A=100, B=400 (Transaction completed successfully after recovery!)

---

## Key Evidence Points Summary

| Evidence Type | Log Keyword | What It Proves |
|--------------|-------------|----------------|
| **Raft Election** | `[Raft Election] *** Elected as LEADER ***` | Leader is dynamically elected, not hardcoded |
| **2PC PREPARE** | `[2PC Layer] Received PREPARE message` | Coordinator correctly sends PREPARE |
| **Raft Replication** | `[Raft Layer] Waiting for majority confirmation` | 2PC decisions require Raft majority |
| **VOTE_COMMIT** | `[2PC Layer] Returning VOTE_COMMIT` | Only votes after Raft confirms |
| **VOTE_ABORT** | `[2PC Layer] Insufficient balance` | Validation correctly rejects |
| **State Machine** | `[State Machine] TX xxx COMMITTED: balance` | Balance only updates on COMMIT |
| **Follower Sync** | `[Raft Follower] Applying committed log` | All replicas stay consistent |
| **Fault Recovery** | `[Raft Election] *** Elected as LEADER (Term 2)` | System recovers after Leader crash |

## Troubleshooting

**No leader elected:**
- Ensure all nodes in the group can communicate
- Check firewall rules for port 5000
- Try `--no-wait` flag: `python3 participant_server.py X --no-wait`

**Connection refused:**
```bash
gcloud compute firewall-rules create allow-2pc-internal \
  --allow tcp:5000 \
  --source-ranges 10.128.0.0/20
```

**Stale state from previous tests:**
```bash
./cleanup.sh
```

**Timeout during PREPARE:**
- Participant may have crashed
- Check all participant servers are running
- Verify network connectivity

## Verification Checklist (Logs to demonstrate)

After running tests, ensure these logs are visible:

### Required Logs (Professor will check)

- [ ] **Raft Election**: `[Raft Election] *** Elected as LEADER (Term X) ***`
- [ ] **Voting Process**: `[Raft Election] Received vote from Node X, current votes: Y/5`
- [ ] **2PC PREPARE**: `[2PC Layer] Received PREPARE message`
- [ ] **Raft Replication**: `[Raft Layer] Replicating PREPARE to Raft Follower nodes...`
- [ ] **Majority Confirmation**: `[Raft Layer] Majority confirmed`
- [ ] **2PC Vote**: `[2PC Layer] Returning VOTE_COMMIT to coordinator`
- [ ] **State Machine Update**: `[State Machine] TX xxx COMMITTED: balance X -> Y`
- [ ] **Follower Sync**: `[Raft Follower] Applying committed log`

### Scenario 1.b Specific
- [ ] **Insufficient Funds**: `[2PC Layer] Insufficient balance: current 90 < required 100`
- [ ] **VOTE_ABORT**: `[2PC Layer] Returning VOTE_ABORT to coordinator`

### Scenario 1.c Specific
- [ ] **New Leader Election**: `[Raft Election] *** Elected as LEADER (Term 2) ***` (Term increased)
