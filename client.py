# -*- coding:utf-8 -*-
"""
CISC 6935 Distributed Systems - Lab 3
Test Client - Run on node0 to test 2PC + Raft scenarios
"""

import time
import pickle
from multiprocessing.connection import Client


class RPCProxy:
    """Proxy for making RPC calls"""
    def __init__(self, connection):
        self._connection = connection

    def __getattr__(self, name):
        def do_rpc(*args, **kwargs):
            try:
                self._connection.send(pickle.dumps((name, args, kwargs)))
                result = pickle.loads(self._connection.recv())
                if isinstance(result, Exception):
                    raise result
                return result
            except Exception as e:
                raise ConnectionError(f"RPC failed: {str(e)}")
        return do_rpc


class Lab3Client:
    """Client for testing 2PC + Raft scenarios"""

    def __init__(self):
        # Coordinator (node1)
        self.coordinator_addr = ('10.128.0.2', 5000)

        # Account A group (nodes 0, 2-5) - 5 nodes
        self.group_a_nodes = [
            (0, '10.128.0.5', 5000),   # node0
            (2, '10.128.0.3', 5000),   # node2
            (3, '10.128.0.4', 5000),   # node3
            (4, '10.128.0.6', 5000),   # node4
            (5, '10.128.0.8', 5000),   # node5
        ]
        
        # Account B group (nodes 6-10) - 5 nodes
        self.group_b_nodes = [
            (6, '10.128.0.10', 5000),  # node6
            (7, '10.128.0.11', 5000),  # node7
            (8, '10.128.0.24', 5000),  # node8
            (9, '10.128.0.25', 5000),  # node9
            (10, '10.128.0.26', 5000), # node10
        ]

    def connect_coordinator(self):
        """Connect to coordinator"""
        try:
            conn = Client(self.coordinator_addr, authkey=b'raft_cluster')
            return RPCProxy(conn)
        except Exception as e:
            print(f"Failed to connect to coordinator: {e}")
            return None

    def connect_participant(self, host, port):
        """Connect to a participant node"""
        try:
            conn = Client((host, port), authkey=b'raft_cluster')
            return RPCProxy(conn)
        except Exception as e:
            print(f"Failed to connect to {host}:{port}: {e}")
            return None

    def check_cluster_status(self):
        """Check status of entire cluster"""
        print("\n" + "=" * 70)
        print("CLUSTER STATUS")
        print("=" * 70)

        # Check coordinator
        print("\n📌 Coordinator (Node 1):")
        coord = self.connect_coordinator()
        if coord:
            status = coord.get_status()
            print(f"   ✓ Online - {status}")
        else:
            print("   ✗ NOT REACHABLE")
            return False

        # Check Group A
        print("\n📌 Group A (Account A) - Nodes 0, 2-5 (5 nodes):")
        group_a_leader = None
        for node_id, host, port in self.group_a_nodes:
            try:
                proxy = self.connect_participant(host, port)
                if proxy:
                    status = proxy.get_status()
                    state = status['state']
                    balance = status['balance']
                    leader_mark = "👑 LEADER" if state == 'leader' else f"   {state}"
                    if state == 'leader':
                        group_a_leader = node_id
                    print(f"   Node {node_id}: {leader_mark}, balance={balance}, log={status['log_length']}")
                else:
                    print(f"   Node {node_id}: ✗ NOT REACHABLE")
            except Exception as e:
                print(f"   Node {node_id}: ✗ ERROR ({e})")

        # Check Group B
        print("\n📌 Group B (Account B) - Nodes 6-10 (5 nodes):")
        group_b_leader = None
        for node_id, host, port in self.group_b_nodes:
            try:
                proxy = self.connect_participant(host, port)
                if proxy:
                    status = proxy.get_status()
                    state = status['state']
                    balance = status['balance']
                    leader_mark = "👑 LEADER" if state == 'leader' else f"   {state}"
                    if state == 'leader':
                        group_b_leader = node_id
                    print(f"   Node {node_id}: {leader_mark}, balance={balance}, log={status['log_length']}")
                else:
                    print(f"   Node {node_id}: ✗ NOT REACHABLE")
            except Exception as e:
                print(f"   Node {node_id}: ✗ ERROR ({e})")

        print("\n" + "=" * 70)
        if group_a_leader is not None and group_b_leader is not None:
            print(f"✓ CLUSTER READY")
            print(f"  Group A Leader: Node {group_a_leader}")
            print(f"  Group B Leader: Node {group_b_leader}")
            return True
        else:
            print("✗ CLUSTER NOT READY - Leaders not elected")
            if group_a_leader is None:
                print("  - Group A has no leader")
            if group_b_leader is None:
                print("  - Group B has no leader")
            return False

    def get_balances(self):
        """Get current balances from coordinator"""
        coord = self.connect_coordinator()
        if coord:
            return coord.get_all_balances()
        return None

    def set_balances(self, balance_a: float, balance_b: float):
        """Set initial balances"""
        coord = self.connect_coordinator()
        if coord:
            return coord.set_initial_balances(balance_a, balance_b)
        return None

    def execute_transfer(self, from_account: str, to_account: str, amount: float):
        """Execute a transfer transaction"""
        if from_account == "A" and to_account == "B":
            operations = {
                "A": {"type": "debit", "amount": amount},
                "B": {"type": "credit", "amount": amount}
            }
        elif from_account == "B" and to_account == "A":
            operations = {
                "A": {"type": "credit", "amount": amount},
                "B": {"type": "debit", "amount": amount}
            }
        else:
            return {"error": "Invalid accounts"}

        coord = self.connect_coordinator()
        if coord:
            return coord.execute_transaction(operations)
        return {"error": "Cannot connect to coordinator"}

    def execute_bonus(self, balance_a: float):
        """Execute T2: 20% bonus to A and same amount to B"""
        bonus = balance_a * 0.2
        operations = {
            "A": {"type": "credit", "amount": bonus},
            "B": {"type": "credit", "amount": bonus}
        }
        coord = self.connect_coordinator()
        if coord:
            return coord.execute_transaction(operations)
        return {"error": "Cannot connect to coordinator"}

    # ==================== Test Scenarios ====================

    def scenario_1a_t1_first(self):
        """
        Scenario 1.a: A=200, B=300, no failures
        Execute T1 first, then T2
        """
        print("\n" + "=" * 70)
        print("SCENARIO 1.a: Normal Operation (A=200, B=300)")
        print("Transaction Order: T1 (Transfer $100 A→B) → T2 (20% Bonus)")
        print("=" * 70)

        # Step 1: Set initial balances
        print("\n[Step 1] Setting initial balances: A=200, B=300")
        result = self.set_balances(200, 300)
        print(f"Result: {result}")
        time.sleep(2)

        # Verify balances
        balances = self.get_balances()
        print(f"Current balances: A={balances['A']}, B={balances['B']}")

        # Step 2: Execute T1 - Transfer $100 from A to B
        print("\n[Step 2] Executing T1: Transfer $100 from A to B")
        print("Expected: A = 200 - 100 = 100, B = 300 + 100 = 400")
        result = self.execute_transfer("A", "B", 100)
        print(f"T1 Result: {result}")
        time.sleep(2)

        balances = self.get_balances()
        print(f"After T1: A={balances['A']}, B={balances['B']}")

        # Verify T1
        if balances['A'] == 100 and balances['B'] == 400:
            print("✓ T1 verification PASSED")
        else:
            print("✗ T1 verification FAILED")

        # Step 3: Execute T2 - 20% bonus
        print("\n[Step 3] Executing T2: Add 20% of A to both A and B")
        print(f"Bonus amount: 20% of {balances['A']} = {balances['A'] * 0.2}")
        print(f"Expected: A = 100 + 20 = 120, B = 400 + 20 = 420")
        result = self.execute_bonus(balances['A'])
        print(f"T2 Result: {result}")
        time.sleep(2)

        balances = self.get_balances()
        print(f"After T2: A={balances['A']}, B={balances['B']}")

        # Verify T2
        if balances['A'] == 120 and balances['B'] == 420:
            print("✓ T2 verification PASSED")
        else:
            print("✗ T2 verification FAILED")

        print("\n" + "=" * 70)
        print("SCENARIO 1.a (T1→T2) COMPLETED")
        print(f"Final: A={balances['A']}, B={balances['B']}")
        print("=" * 70)

    def scenario_1a_t2_first(self):
        """
        Scenario 1.a: A=200, B=300, no failures
        Execute T2 first, then T1
        """
        print("\n" + "=" * 70)
        print("SCENARIO 1.a: Normal Operation (A=200, B=300)")
        print("Transaction Order: T2 (20% Bonus) → T1 (Transfer $100 A→B)")
        print("=" * 70)

        # Step 1: Set initial balances
        print("\n[Step 1] Setting initial balances: A=200, B=300")
        result = self.set_balances(200, 300)
        time.sleep(2)

        balances = self.get_balances()
        print(f"Current balances: A={balances['A']}, B={balances['B']}")

        # Step 2: Execute T2 first
        print("\n[Step 2] Executing T2: Add 20% of A to both A and B")
        print(f"Bonus amount: 20% of 200 = 40")
        print(f"Expected: A = 200 + 40 = 240, B = 300 + 40 = 340")
        result = self.execute_bonus(200)  # Use initial balance
        print(f"T2 Result: {result}")
        time.sleep(2)

        balances = self.get_balances()
        print(f"After T2: A={balances['A']}, B={balances['B']}")

        # Step 3: Execute T1
        print("\n[Step 3] Executing T1: Transfer $100 from A to B")
        print(f"Expected: A = 240 - 100 = 140, B = 340 + 100 = 440")
        result = self.execute_transfer("A", "B", 100)
        print(f"T1 Result: {result}")
        time.sleep(2)

        balances = self.get_balances()
        print(f"After T1: A={balances['A']}, B={balances['B']}")

        print("\n" + "=" * 70)
        print("SCENARIO 1.a (T2→T1) COMPLETED")
        print(f"Final: A={balances['A']}, B={balances['B']}")
        print("=" * 70)

    def scenario_1b_t1_first(self):
        """
        Scenario 1.b: A=90, B=50, no failures
        T1 first - should FAIL (A has insufficient funds for $100 transfer)
        """
        print("\n" + "=" * 70)
        print("SCENARIO 1.b: Insufficient Funds (A=90, B=50)")
        print("Transaction Order: T1 (Transfer $100 A→B) → T2 (20% Bonus)")
        print("=" * 70)

        # Step 1: Set initial balances
        print("\n[Step 1] Setting initial balances: A=90, B=50")
        result = self.set_balances(90, 50)
        time.sleep(2)

        balances = self.get_balances()
        print(f"Current balances: A={balances['A']}, B={balances['B']}")

        # Step 2: Execute T1 - should FAIL
        print("\n[Step 2] Executing T1: Transfer $100 from A to B")
        print("Expected: ABORT (A=90 < 100, insufficient funds)")
        result = self.execute_transfer("A", "B", 100)
        print(f"T1 Result: {result}")
        time.sleep(2)

        balances = self.get_balances()
        print(f"After T1 (should be unchanged): A={balances['A']}, B={balances['B']}")

        if result.get('status') == 'ABORTED':
            print("✓ T1 correctly ABORTED")
        else:
            print("✗ T1 should have ABORTED but didn't!")

        # Step 3: Execute T2 - should SUCCEED
        print("\n[Step 3] Executing T2: Add 20% of A to both A and B")
        print(f"Bonus amount: 20% of 90 = 18")
        print(f"Expected: A = 90 + 18 = 108, B = 50 + 18 = 68")
        result = self.execute_bonus(90)
        print(f"T2 Result: {result}")
        time.sleep(2)

        balances = self.get_balances()
        print(f"After T2: A={balances['A']}, B={balances['B']}")

        if result.get('status') == 'COMMITTED':
            print("✓ T2 correctly COMMITTED")
        else:
            print("✗ T2 should have COMMITTED")

        print("\n" + "=" * 70)
        print("SCENARIO 1.b (T1→T2) COMPLETED")
        print(f"Final: A={balances['A']}, B={balances['B']}")
        print("T1: ABORTED (insufficient funds)")
        print("T2: COMMITTED")
        print("=" * 70)

    def scenario_1b_t2_first(self):
        """
        Scenario 1.b: A=90, B=50, no failures
        T2 first - should SUCCEED
        """
        print("\n" + "=" * 70)
        print("SCENARIO 1.b: Insufficient Funds (A=90, B=50)")
        print("Transaction Order: T2 (20% Bonus) → T1 (Transfer $100 A→B)")
        print("=" * 70)

        # Step 1: Set initial balances
        print("\n[Step 1] Setting initial balances: A=90, B=50")
        result = self.set_balances(90, 50)
        time.sleep(2)

        balances = self.get_balances()
        print(f"Current balances: A={balances['A']}, B={balances['B']}")

        # Step 2: Execute T2 first - should SUCCEED
        print("\n[Step 2] Executing T2: Add 20% of A to both A and B")
        print(f"Bonus amount: 20% of 90 = 18")
        print(f"Expected: A = 90 + 18 = 108, B = 50 + 18 = 68")
        result = self.execute_bonus(90)
        print(f"T2 Result: {result}")
        time.sleep(2)

        balances = self.get_balances()
        print(f"After T2: A={balances['A']}, B={balances['B']}")

        # Step 3: Execute T1 - should SUCCEED now (A=108 >= 100)
        print("\n[Step 3] Executing T1: Transfer $100 from A to B")
        print(f"Expected: A = 108 - 100 = 8, B = 68 + 100 = 168")
        result = self.execute_transfer("A", "B", 100)
        print(f"T1 Result: {result}")
        time.sleep(2)

        balances = self.get_balances()
        print(f"After T1: A={balances['A']}, B={balances['B']}")

        print("\n" + "=" * 70)
        print("SCENARIO 1.b (T2→T1) COMPLETED")
        print(f"Final: A={balances['A']}, B={balances['B']}")
        print("T2: COMMITTED")
        print("T1: COMMITTED (after bonus, A had enough)")
        print("=" * 70)

    def scenario_1c_i(self):
        """
        Scenario 1.c.i: Participant crashes BEFORE voting (ABORT recovery)
        Node crashes before responding to PREPARE
        """
        print("\n" + "=" * 70)
        print("SCENARIO 1.c.i: Participant Crash Before Voting")
        print("=" * 70)

        print("\n[Setup] Setting initial balances: A=200, B=300")
        self.set_balances(200, 300)
        time.sleep(2)

        print("\n⚠️  MANUAL ACTION REQUIRED:")
        print("  1. On one of the Group A nodes (e.g., the leader), press Ctrl+C")
        print("     to crash it BEFORE this test sends the PREPARE message.")
        print("  2. The coordinator should timeout waiting for PREPARE response")
        print("  3. The entire transaction should ABORT")
        print("\nPress Enter when you've crashed the node...")
        input()

        print("\n[Test] Executing T1: Transfer $100 from A to B")
        print("Expected: ABORT due to timeout waiting for crashed participant")
        result = self.execute_transfer("A", "B", 100)
        print(f"Result: {result}")

        if result.get('status') == 'ABORTED':
            print("\n✓ Transaction correctly ABORTED due to participant unavailability")
        else:
            print("\n⚠️ Unexpected result")

        balances = self.get_balances()
        print(f"\nFinal balances (should be unchanged): A={balances.get('A')}, B={balances.get('B')}")

        print("\n" + "=" * 70)
        print("SCENARIO 1.c.i COMPLETED")
        print("=" * 70)

    def scenario_1c_ii(self):
        """
        Scenario 1.c.ii: Participant crashes AFTER voting COMMIT (recovery)
        Node crashes after sending VOTE_COMMIT but before receiving COMMIT
        """
        print("\n" + "=" * 70)
        print("SCENARIO 1.c.ii: Participant Crash After Voting")
        print("=" * 70)

        print("\n[Setup] Setting initial balances: A=200, B=300")
        self.set_balances(200, 300)
        time.sleep(2)

        balances = self.get_balances()
        print(f"Initial balances: A={balances['A']}, B={balances['B']}")

        print("\n📋 This scenario demonstrates crash recovery:")
        print("  1. Transaction starts, participant votes VOTE_COMMIT")
        print("  2. A 10-second pause gives you time to crash the participant")
        print("  3. Coordinator still commits (has all votes)")
        print("  4. After restart, crashed participant recovers its state")

        print("\n[Step 1] Enabling crash demo mode on Group A leader...")
        # Find Group A leader
        group_a_leader = None
        for node_id, host, port in self.group_a_nodes:
            try:
                proxy = self.connect_participant(host, port)
                if proxy:
                    status = proxy.get_status()
                    if status['state'] == 'leader':
                        group_a_leader = (node_id, host, port)
                        print(f"  Found Group A leader: Node {node_id}")
                        # Enable crash demo mode
                        proxy.enable_crash_demo(True)
                        break
            except:
                pass

        if not group_a_leader:
            print("  ERROR: No Group A leader found!")
            return

        print("\n⚠️  INSTRUCTIONS:")
        print(f"  1. Watch the terminal of Node {group_a_leader[0]} (Group A Leader)")
        print("  2. When you see '!!! PAUSE FOR 1.c.ii CRASH DEMO !!!', press Ctrl+C on that terminal")
        print("  3. The transaction will complete on the Coordinator side")
        print("  4. Then restart the crashed node to see recovery")

        print("\nPress Enter to start the transaction...")
        input()

        print("\n[Step 2] Executing T1: Transfer $100 from A to B")
        result = self.execute_transfer("A", "B", 100)
        print(f"Result: {result}")

        print("\n⚠️  If you crashed the node, restart it now:")
        print(f"  python3 participant_server.py {group_a_leader[0]}")
        print("\nPress Enter after restarting the node...")
        input()

        time.sleep(5)  # Wait for node to sync

        print("\n[Step 3] Verification - Checking final state...")
        # Disable crash demo mode on new leader
        for node_id, host, port in self.group_a_nodes:
            try:
                proxy = self.connect_participant(host, port)
                if proxy:
                    status = proxy.get_status()
                    if status['state'] == 'leader':
                        proxy.enable_crash_demo(False)
            except:
                pass

        balances = self.get_balances()
        print(f"Final balances: A={balances.get('A')}, B={balances.get('B')}")

        self.verify_raft_replication()

        print("\n" + "=" * 70)
        print("SCENARIO 1.c.ii COMPLETED")
        print("All nodes should show consistent state after recovery")
        print("=" * 70)

    def scenario_1c_iii(self):
        """
        Scenario 1.c.iii: Coordinator crashes after receiving all VOTE_COMMITs (6935 only)
        Coordinator crashes before sending COMMIT, then recovers
        """
        print("\n" + "=" * 70)
        print("SCENARIO 1.c.iii: Coordinator Crash (6935 Only)")
        print("=" * 70)

        print("\n[Setup] Setting initial balances: A=200, B=300")
        self.set_balances(200, 300)
        time.sleep(2)

        balances = self.get_balances()
        print(f"Initial balances: A={balances['A']}, B={balances['B']}")

        print("\n📋 This scenario demonstrates coordinator crash recovery:")
        print("  1. Coordinator sends PREPARE to all participants")
        print("  2. All participants vote VOTE_COMMIT")
        print("  3. A 10-second pause gives you time to crash the coordinator")
        print("  4. Participants are in PREPARED state (holding locks)")
        print("  5. Coordinator recovers, finds incomplete TX in log, resumes COMMIT")

        print("\n[Step 1] Enabling crash demo mode on Coordinator...")
        coord = self.connect_coordinator()
        if coord:
            coord.enable_crash_demo(True)
            print("  Crash demo mode ENABLED on Coordinator")
        else:
            print("  ERROR: Cannot connect to Coordinator!")
            return

        print("\n⚠️  INSTRUCTIONS:")
        print("  1. Watch the terminal of Node 1 (Coordinator)")
        print("  2. When you see '!!! PAUSE FOR 1.c.iii CRASH DEMO !!!', press Ctrl+C on that terminal")
        print("  3. The participants will be stuck in PREPARED state")
        print("  4. Then restart the coordinator to see recovery")

        print("\nPress Enter to start the transaction...")
        input()

        print("\n[Step 2] Executing T1: Transfer $100 from A to B")
        print("⚠️  WATCH THE COORDINATOR TERMINAL - CRASH IT WHEN YOU SEE THE PAUSE!")

        try:
            result = self.execute_transfer("A", "B", 100)
            print(f"Result: {result}")
            print("\n(If you see this, you didn't crash the coordinator in time)")
        except Exception as e:
            print(f"Expected: Connection lost due to coordinator crash")
            print(f"Error: {e}")

        print("\n⚠️  If you crashed the coordinator, restart it now:")
        print("  python3 coordinator_server.py")
        print("\n  The coordinator will:")
        print("  1. Load coordinator_tx_log.json")
        print("  2. Find the incomplete transaction")
        print("  3. Resume Phase 2: send COMMIT to participants")
        print("\nPress Enter after restarting the coordinator...")
        input()

        time.sleep(3)  # Wait for recovery

        print("\n[Step 3] Verification - Checking final state...")
        balances = self.get_balances()
        print(f"Final balances: A={balances.get('A')}, B={balances.get('B')}")

        expected_a = 100  # 200 - 100
        expected_b = 400  # 300 + 100

        if balances.get('A') == expected_a and balances.get('B') == expected_b:
            print(f"\n✓ SUCCESS: Transaction completed after coordinator recovery!")
            print(f"  A: 200 -> {expected_a} (debited $100)")
            print(f"  B: 300 -> {expected_b} (credited $100)")
        else:
            print(f"\n⚠️  Balances don't match expected values")
            print(f"  Expected: A={expected_a}, B={expected_b}")
            print(f"  Got: A={balances.get('A')}, B={balances.get('B')}")

        self.verify_raft_replication()

        print("\n" + "=" * 70)
        print("SCENARIO 1.c.iii COMPLETED")
        print("The coordinator successfully recovered and completed the transaction!")
        print("=" * 70)

    def verify_raft_replication(self):
        """Verify that Raft is replicating 2PC decisions correctly"""
        print("\n" + "=" * 70)
        print("RAFT REPLICATION VERIFICATION")
        print("=" * 70)

        print("\n📋 Checking log consistency across all nodes...")

        # Check Group A
        print("\n[Group A - Account A] (Nodes 0, 2-5)")
        for node_id, host, port in self.group_a_nodes:
            try:
                proxy = self.connect_participant(host, port)
                if proxy:
                    status = proxy.get_status()
                    print(f"  Node {node_id}: log_len={status['log_length']}, "
                          f"commit={status['commit_index']}, "
                          f"balance={status['balance']}, "
                          f"state={status['state']}")
            except Exception as e:
                print(f"  Node {node_id}: ERROR ({e})")

        # Check Group B
        print("\n[Group B - Account B] (Nodes 6-10)")
        for node_id, host, port in self.group_b_nodes:
            try:
                proxy = self.connect_participant(host, port)
                if proxy:
                    status = proxy.get_status()
                    print(f"  Node {node_id}: log_len={status['log_length']}, "
                          f"commit={status['commit_index']}, "
                          f"balance={status['balance']}, "
                          f"state={status['state']}")
            except Exception as e:
                print(f"  Node {node_id}: ERROR ({e})")

        print("\n" + "=" * 70)

    def run_all_scenarios(self):
        """Run all test scenarios"""
        print("\n" + "=" * 70)
        print("LAB 3: 2PC + RAFT COMPLETE TEST SUITE")
        print("=" * 70)

        if not self.check_cluster_status():
            print("\n✗ Cluster not ready. Please start all servers first.")
            return

        print("\n\n" + "=" * 70)
        print("SELECT SCENARIO TO RUN:")
        print("=" * 70)
        print("  1. Scenario 1.a (T1→T2): A=200, B=300, Transfer then Bonus")
        print("  2. Scenario 1.a (T2→T1): A=200, B=300, Bonus then Transfer")
        print("  3. Scenario 1.b (T1→T2): A=90, B=50, T1 FAILS, T2 succeeds")
        print("  4. Scenario 1.b (T2→T1): A=90, B=50, T2 then T1 both succeed")
        print("  5. Scenario 1.c.i: Participant crash BEFORE voting")
        print("  6. Scenario 1.c.ii: Participant crash AFTER voting")
        print("  7. Scenario 1.c.iii: Coordinator crash (6935)")
        print("  8. Verify Raft replication")
        print("  9. Run ALL normal scenarios (1.a, 1.b)")
        print("  0. Exit")

        while True:
            choice = input("\nEnter choice: ").strip()

            if choice == '1':
                self.scenario_1a_t1_first()
            elif choice == '2':
                self.scenario_1a_t2_first()
            elif choice == '3':
                self.scenario_1b_t1_first()
            elif choice == '4':
                self.scenario_1b_t2_first()
            elif choice == '5':
                self.scenario_1c_i()
            elif choice == '6':
                self.scenario_1c_ii()
            elif choice == '7':
                self.scenario_1c_iii()
            elif choice == '8':
                self.verify_raft_replication()
            elif choice == '9':
                print("\n>>> Running Scenario 1.a (T1→T2)")
                self.scenario_1a_t1_first()
                input("\nPress Enter to continue to next scenario...")

                print("\n>>> Running Scenario 1.a (T2→T1)")
                self.scenario_1a_t2_first()
                input("\nPress Enter to continue to next scenario...")

                print("\n>>> Running Scenario 1.b (T1→T2)")
                self.scenario_1b_t1_first()
                input("\nPress Enter to continue to next scenario...")

                print("\n>>> Running Scenario 1.b (T2→T1)")
                self.scenario_1b_t2_first()
            elif choice == '0':
                break
            else:
                print("Invalid choice")


if __name__ == '__main__':
    client = Lab3Client()

    print("=" * 70)
    print("CISC 6935 Lab 3: 2PC + Raft Test Client")
    print("=" * 70)

    print("\nChecking cluster status...")
    client.check_cluster_status()

    print("\nOptions:")
    print("  1. Run test scenarios")
    print("  2. Check cluster status only")
    print("  3. Quick transfer test (A=200, B=300, transfer $100)")
    print("  4. Verify Raft replication")

    choice = input("\nEnter choice (1/2/3/4): ").strip()

    if choice == '1':
        client.run_all_scenarios()
    elif choice == '2':
        pass  # Already showed status
    elif choice == '3':
        print("\nSetting A=200, B=300...")
        client.set_balances(200, 300)
        time.sleep(2)
        print("\nExecuting transfer $100 from A to B...")
        result = client.execute_transfer("A", "B", 100)
        print(f"Result: {result}")
        time.sleep(2)
        balances = client.get_balances()
        print(f"Final balances: A={balances['A']}, B={balances['B']}")
    elif choice == '4':
        client.verify_raft_replication()
