# Lab 3 Demo Script (Video Recording Guide)

## Pre-Demo Setup

### Terminal Windows Required (11 SSH connections)

| Terminal | Node | IP | Role |
|----------|------|-----|------|
| Terminal 1 | node1 | 10.128.0.2 | Coordinator |
| Terminal 2 | node0 | 10.128.0.5 | Account A - Raft |
| Terminal 3 | node2 | 10.128.0.3 | Account A - Raft |
| Terminal 4 | node3 | 10.128.0.4 | Account A - Raft |
| Terminal 5 | node4 | 10.128.0.6 | Account A - Raft |
| Terminal 6 | node5 | 10.128.0.8 | Account A - Raft |
| Terminal 7 | node6 | 10.128.0.10 | Account B - Raft |
| Terminal 8 | node7 | 10.128.0.11 | Account B - Raft |
| Terminal 9 | node8 | 10.128.0.24 | Account B - Raft |
| Terminal 10 | node9 | 10.128.0.25 | Account B - Raft |
| Terminal 11 | node10 | 10.128.0.26 | Account B - Raft |
| Terminal 12 | Any | - | Client (run tests) |

---

## Step 1: Clean Old State (30 seconds)

### Script:
> "First, let's clean up all state files on every node to ensure a fresh start."

### Action:
Run on **each node**:
```bash
rm -f raft_state_*.json raft_log_*.log account_*.dat coordinator_tx_log.json
```

Or use the cleanup script:
```bash
./cleanup.sh
```

---

## Step 2: Start Coordinator (20 seconds)

### Script:
> "Now let's start the 2PC Coordinator on node1. It manages distributed transactions across both account groups."

### Action (Terminal 1 - node1):
```bash
python3 coordinator_server.py
```

### Expected Output:
```
============================================================
Starting 2PC Coordinator (Node 1)
Listening on: 0.0.0.0:5000
Group A nodes: [0, 2, 3, 4, 5]
Group B nodes: [6, 7, 8, 9, 10]
============================================================
[Coordinator] Server started. Waiting for connections...
```

---

## Step 3: Start Account A Raft Nodes (1 minute)

### Script:
> "Next, we start the 5 Raft nodes for Account A. These nodes will conduct a leader election using the Raft consensus protocol."

### Action (Terminals 2-6):

**Terminal 2 (node0):**
```bash
python3 participant_server.py 0
```

**Terminal 3 (node2):**
```bash
python3 participant_server.py 2
```

**Terminal 4 (node3):**
```bash
python3 participant_server.py 3
```

**Terminal 5 (node4):**
```bash
python3 participant_server.py 4
```

**Terminal 6 (node5):**
```bash
python3 participant_server.py 5
```

### Expected Output (Leader Election):
```
[A-Node X] [Raft Election] Starting election, Term=1
[A-Node X] [Raft Election] Voted for self, current votes: 1/5
[A-Node Y] [Raft Election] Received vote request from Node X (Term 1)
[A-Node Y] [Raft Election] Voted for Node X (Term 1)
[A-Node X] [Raft Election] Received vote from Node Y, current votes: 2/5 (need 3)
...
============================================================
[A-Node X] [Raft Election] Received 3/5 votes
[A-Node X] [Raft Election] *** Elected as LEADER (Term 1) ***
============================================================
```

### Script (after election):
> "As you can see, Node X received majority votes and became the Leader for Account A group. This leader was dynamically elected through Raft consensus, not hardcoded."

---

## Step 4: Start Account B Raft Nodes (1 minute)

### Script:
> "Similarly, let's start the 5 Raft nodes for Account B. They will also conduct leader election."

### Action (Terminals 7-11):

**Terminal 7 (node6):**
```bash
python3 participant_server.py 6
```

**Terminal 8 (node7):**
```bash
python3 participant_server.py 7
```

**Terminal 9 (node8):**
```bash
python3 participant_server.py 8
```

**Terminal 10 (node9):**
```bash
python3 participant_server.py 9
```

**Terminal 11 (node10):**
```bash
python3 participant_server.py 10
```

### Script (after election):
> "Account B group has also completed leader election. Both Raft clusters are now ready to handle 2PC transactions."

---

## Step 5: Run Client Tests (Terminal 12)

### Script:
> "Now let's run the test client to verify the entire system."

### Action:
```bash
python3 client.py
```

Select `1` to run test scenarios.

---

## Scenario 1.a: Normal Operation (A=200, B=300)

### 1.a.1: T1 First (Transfer then Bonus)

### Script:
> "First, let's test Scenario 1.a with initial balances A=200, B=300, no failures.
> We execute T1 first: transfer $100 from A to B."

### Action:
In client, select `1` (Scenario 1.a T1 then T2)

### Logs to Highlight:

**Coordinator window:**
> "Looking at the Coordinator log, it first sends PREPARE messages to both participant group leaders..."
> "Group A returns VOTE_COMMIT, Group B also returns VOTE_COMMIT..."
> "All participants voted COMMIT, so we enter Phase 2 and send COMMIT messages..."
> "Transaction committed successfully. A becomes 100, B becomes 400."

**Account A Leader window:**
> "Now look at the Account A Leader log. This shows our two-layer architecture..."
> "First, the 2PC layer: receives PREPARE, validates that balance 200 is enough to debit 100..."
> "Then the Raft layer: adds PREPARE to Raft log, replicates to the other 4 nodes..."
> "Only AFTER Raft majority confirms, it returns VOTE_COMMIT to Coordinator..."
> "This is the key integration: every 2PC decision requires Raft consensus first."

**Account A Follower window:**
> "Looking at a Follower node, it receives AppendEntries from the Leader, replicating PREPARE and COMMIT logs..."
> "All 5 Account A nodes now have identical logs and balances."

### Script (T2 execution):
> "Now execute T2: add 20% bonus to both accounts.
> Since A=100 now, the bonus is 20.
> Final result: A=120, B=420."

---

### 1.a.2: T2 First (Bonus then Transfer)

### Script:
> "Now let's test the other order: T2 first, then T1.
> Initial: A=200, B=300.
> T2 executes first: bonus is 20% of 200 = 40, so A=240, B=340.
> T1 executes: transfer 100 from A to B, A=140, B=440.
> Different order, different result, but both transactions succeed."

---

## Scenario 1.b: Insufficient Funds (A=90, B=50)

### 1.b.1: T1 First (T1 ABORTS)

### Script:
> "Scenario 1.b tests insufficient funds. Initial: A=90, B=50.
> T1 tries to transfer $100 from A, but A only has $90."

### Action:
In client, select `3` (Scenario 1.b T1 then T2)

### Logs to Highlight:

**Account A Leader window:**
> "Look at the Account A Leader log..."
> "Receives PREPARE, validation FAILS! Balance 90 is less than required 100..."
> "Returns VOTE_ABORT to Coordinator, not VOTE_COMMIT."

**Coordinator window:**
> "Coordinator receives VOTE_ABORT from Group A..."
> "Since not all participants voted COMMIT, the entire transaction ABORTs..."
> "Sends ABORT message to all participants."

### Script:
> "After T1 fails, A and B balances remain unchanged at 90 and 50.
> Then T2 executes: bonus is 20% of 90 = 18.
> T2 succeeds, A=108, B=68."

---

### 1.b.2: T2 First (Both Succeed)

### Script:
> "What if we execute T2 first, then T1?
> T2 first: A=90+18=108, B=50+18=68.
> T1 then: now A=108, enough to debit 100!
> T1 succeeds, final: A=8, B=168.
> This demonstrates how transaction order affects the outcome."

---

## Scenario 1.c.i: Participant Crash Before Voting (Timeout ABORT)

### Script:
> "Scenario 1.c.i tests participant crash before voting."

### Action:
1. In client, select `5` (Scenario 1.c.i)
2. When prompted, press Ctrl+C on the Account A Leader node

### Logs to Highlight:

**Coordinator window:**
> "Coordinator sends PREPARE and waits for Account A's response..."
> "But Account A Leader has crashed, so it times out..."
> "Group A returns VOTE_ABORT (timeout), entire transaction ABORTs."

### Script:
> "This demonstrates 2PC safety: if any participant doesn't respond, the entire transaction ABORTs, guaranteeing atomicity."

---

## Scenario 1.c.ii: Participant Crash After Voting (Recovery)

### Script:
> "Scenario 1.c.ii is more complex: participant crashes after voting COMMIT but before receiving the COMMIT decision."

### Action:
1. In client, select `6` (Scenario 1.c.ii)
2. Watch the logs. When you see VOTE_COMMIT, quickly press Ctrl+C on the Leader node
3. Wait for Coordinator to complete
4. Restart the crashed node

### Logs to Highlight:

**Before crash:**
> "Account A Leader sent VOTE_COMMIT..."
> "Then it crashed!"

**Coordinator continues:**
> "Coordinator already received all VOTE_COMMITs, decides to COMMIT..."
> "Even though Account A Leader crashed, Coordinator completes the transaction."

**After restart:**
> "Restarting the Account A node..."
> "Upon recovery, it finds a PREPARED but not COMMITted transaction in Raft log..."
> "Queries Coordinator, learns the decision was COMMIT..."
> "Applies COMMIT, balance updated."

### Script:
> "This demonstrates Raft durability: even if a node crashes, the PREPARED state is already persisted to Raft majority.
> After recovery, it can continue to complete the transaction, guaranteeing atomicity."

---

## Scenario 1.c.iii: Leader Crash and Re-election (6935 Only)

### Script:
> "Finally, let's test leader crash and re-election, demonstrating Raft's high availability."

### Action:
1. Press Ctrl+C on the Account A Leader node
2. Watch the other Account A nodes

### Logs to Highlight:

**Other Account A nodes:**
> "Election timeout, starting new election..."
> "Term increases from 1 to 2..."
> "Node 3 starts requesting votes..."
> "Receives majority votes, becomes the new Leader!"

### Script:
> "This is the core value of Raft: when a Leader crashes, other nodes automatically elect a new Leader.
> The system continues running, ensuring high availability.
> The new Leader can continue handling 2PC requests without service interruption."

---

## Summary (30 seconds)

### Script:
> "To summarize this Lab 3 implementation:
> 
> 1. **11-Node Architecture**: 1 Coordinator + 5 Account A nodes + 5 Account B nodes
> 
> 2. **Two-Layer Architecture**:
>    - Layer 1: 2PC protocol ensures distributed transaction atomicity
>    - Layer 2: Raft consensus ensures high availability within each participant group
> 
> 3. **Key Integration Points**:
>    - Every 2PC PREPARE and COMMIT decision must first be replicated to Raft majority
>    - Only after majority confirmation does it return the vote to Coordinator
>    - This ensures state is never lost even if nodes crash
> 
> 4. **Fault Tolerance**:
>    - Participant crash: Transaction ABORTs or waits for recovery
>    - Leader crash: Raft automatically elects new Leader
>    - All nodes maintain consistent logs and state
> 
> Demo complete. Thank you!"

---

## Recording Checklist

Before recording, ensure you demonstrate these logs:

- [ ] **Raft Election**: `[Raft Election] *** Elected as LEADER (Term X) ***`
- [ ] **Voting Process**: `[Raft Election] Received vote from Node X, current votes: Y/5`
- [ ] **2PC PREPARE**: `[2PC Layer] Received PREPARE message`
- [ ] **Raft Replication**: `[Raft Layer] Replicating PREPARE to Raft Follower nodes...`
- [ ] **Majority Confirmation**: `[Raft Layer] Majority confirmed`
- [ ] **Vote Result**: `[2PC Layer] Returning VOTE_COMMIT to coordinator`
- [ ] **State Machine Update**: `[State Machine] TX xxx COMMITTED: balance X -> Y`
- [ ] **Follower Sync**: `[Raft Follower] Applying committed log entry`
- [ ] **(1.b) VOTE_ABORT**: `[2PC Layer] Insufficient balance: 90 < 100`
- [ ] **(1.c) New Leader Election**: Election log with increased Term

---

## Quick Command Reference

```bash
# Clean all state
rm -f raft_state_*.json raft_log_*.log account_*.dat coordinator_tx_log.json

# Start Coordinator (node1)
python3 coordinator_server.py

# Start Account A (nodes 0, 2-5)
python3 participant_server.py 0
python3 participant_server.py 2
python3 participant_server.py 3
python3 participant_server.py 4
python3 participant_server.py 5

# Start Account B (nodes 6-10)
python3 participant_server.py 6
python3 participant_server.py 7
python3 participant_server.py 8
python3 participant_server.py 9
python3 participant_server.py 10

# Run tests
python3 client.py
```
