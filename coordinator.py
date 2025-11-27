# -*- coding:utf-8 -*-
"""
CISC 6935 Distributed Systems - Lab 3
2PC Coordinator Node
Manages distributed transactions across Account A and Account B groups
"""

import time
import threading
import json
import os
import uuid
from enum import Enum
from typing import Dict, List, Optional
from multiprocessing.connection import Client
import pickle


class TxStatus(Enum):
    """Transaction status"""
    PENDING = "pending"
    PREPARING = "preparing"
    PREPARED = "prepared"
    COMMITTING = "committing"
    COMMITTED = "committed"
    ABORTING = "aborting"
    ABORTED = "aborted"


class RPCProxy:
    """Proxy for making RPC calls to participant nodes"""
    def __init__(self, connection):
        self._connection = connection
        self._lock = threading.Lock()

    def __getattr__(self, name):
        def do_rpc(*args, **kwargs):
            with self._lock:
                try:
                    self._connection.send(pickle.dumps((name, args, kwargs)))
                    if self._connection.poll(timeout=10.0):  # Longer timeout for 2PC
                        result = pickle.loads(self._connection.recv())
                        if isinstance(result, Exception):
                            raise result
                        return result
                    else:
                        raise ConnectionError(f"RPC timeout")
                except (EOFError, ConnectionResetError, BrokenPipeError) as e:
                    raise ConnectionError(f"Connection lost: {str(e)}")
        return do_rpc


class Coordinator:
    """
    2PC Coordinator
    Manages distributed transactions across two participant groups (A and B)
    """

    def __init__(self, node_id: int = 1, port: int = 5000):
        self.node_id = node_id
        self.port = port

        # Participant groups configuration
        # Each group has multiple Raft nodes, but we communicate with the leader
        self.group_a_nodes = []  # List of (node_id, host, port)
        self.group_b_nodes = []

        # Transaction log (for crash recovery)
        self.tx_log = {}  # {tx_id: {"status": TxStatus, "participants": [...], "decision": ...}}
        self.tx_log_file = "coordinator_tx_log.json"

        # Connection cache
        self.connections = {}  # {(host, port): RPCProxy}

        # Lock for thread safety
        self.lock = threading.Lock()

        # Timeout settings
        self.prepare_timeout = 10.0  # seconds to wait for PREPARE responses
        self.commit_timeout = 10.0
        
        # Crash demo mode - adds pauses for manual crash testing
        self.crash_demo_mode = False

        print(f"[Coordinator] Initialized on node {node_id}")

    def set_participant_groups(self, group_a: List[tuple], group_b: List[tuple]):
        """Set participant group configurations"""
        self.group_a_nodes = group_a
        self.group_b_nodes = group_b
        print(f"[Coordinator] Group A nodes: {[n[0] for n in group_a]}")
        print(f"[Coordinator] Group B nodes: {[n[0] for n in group_b]}")

    def load_tx_log(self):
        """Load transaction log from disk (for crash recovery)"""
        if os.path.exists(self.tx_log_file):
            try:
                with open(self.tx_log_file, 'r') as f:
                    data = json.load(f)
                    for tx_id, tx_data in data.items():
                        tx_data["status"] = TxStatus(tx_data["status"])
                    self.tx_log = data
                print(f"[Coordinator] Loaded {len(self.tx_log)} transactions from log")
            except Exception as e:
                print(f"[Coordinator] Error loading tx log: {e}")

    def save_tx_log(self):
        """Save transaction log to disk"""
        data = {}
        for tx_id, tx_data in self.tx_log.items():
            data[tx_id] = {
                "status": tx_data["status"].value if isinstance(tx_data["status"], TxStatus) else tx_data["status"],
                "participants": tx_data.get("participants", []),
                "decision": tx_data.get("decision"),
                "operations": tx_data.get("operations", {}),
                "votes": tx_data.get("votes", {})
            }
        with open(self.tx_log_file, 'w') as f:
            json.dump(data, f, indent=2)

    def enable_crash_demo(self, mode: str = None):
        """
        Enable or disable crash demo mode
        mode: "1.c.ii" - pause for participant crash demo
              "1.c.iii" - pause for coordinator crash demo
              None/False - disable
        """
        self.crash_demo_mode = mode
        if mode:
            print(f"[Coordinator] Crash demo mode: {mode} ENABLED")
            print(f"[Coordinator] A 10-second pause will be added before COMMIT phase")
            if mode == "1.c.ii":
                print(f"[Coordinator] During pause: CRASH THE PARTICIPANT LEADER")
            elif mode == "1.c.iii":
                print(f"[Coordinator] During pause: CRASH THIS COORDINATOR")
        else:
            print(f"[Coordinator] Crash demo mode: DISABLED")

    def recover_incomplete_transactions(self):
        """
        Check for and recover any incomplete transactions after crash recovery.
        This is called after loading the transaction log on startup.
        """
        print(f"\n[Coordinator] ========== CRASH RECOVERY ==========")
        print(f"[Coordinator] Checking for incomplete transactions...")
        
        recovered = 0
        for tx_id, tx_data in list(self.tx_log.items()):
            status = tx_data.get("status")
            decision = tx_data.get("decision")
            
            # Convert string status to TxStatus if needed
            if isinstance(status, str):
                status = TxStatus(status)
            
            print(f"[Coordinator] TX {tx_id}: status={status.value if isinstance(status, TxStatus) else status}, decision={decision}")
            
            # Case 1: Decision was COMMIT but transaction didn't complete
            if decision == "COMMIT" and status != TxStatus.COMMITTED:
                print(f"\n[Coordinator] [Recovery] Found incomplete COMMIT for TX {tx_id}")
                print(f"[Coordinator] [Recovery] Resuming Phase 2: COMMIT...")
                
                # Find current leaders and resend COMMIT
                operations = tx_data.get("operations", {})
                leaders = {}
                
                if "A" in operations or "A" in tx_data.get("participants", []):
                    leader_a = self.find_group_leader(self.group_a_nodes)
                    if leader_a:
                        leaders["A"] = leader_a
                        print(f"[Coordinator] [Recovery] Group A leader: Node {leader_a[0]}")
                
                if "B" in operations or "B" in tx_data.get("participants", []):
                    leader_b = self.find_group_leader(self.group_b_nodes)
                    if leader_b:
                        leaders["B"] = leader_b
                        print(f"[Coordinator] [Recovery] Group B leader: Node {leader_b[0]}")
                
                # Send COMMIT to all participants
                for group, (node_id, host, port) in leaders.items():
                    try:
                        print(f"[Coordinator] [Recovery] Sending COMMIT to Group {group} (Node {node_id})")
                        proxy = self.get_connection(host, port)
                        if proxy:
                            result = proxy.commit(tx_id)
                            print(f"[Coordinator] [Recovery] Group {group} COMMIT result: {result}")
                    except Exception as e:
                        print(f"[Coordinator] [Recovery] Error sending COMMIT to Group {group}: {e}")
                
                # Mark as committed
                self.tx_log[tx_id]["status"] = TxStatus.COMMITTED
                self.save_tx_log()
                print(f"[Coordinator] [Recovery] TX {tx_id} COMMITTED successfully")
                recovered += 1
            
            # Case 2: Decision was ABORT but transaction didn't complete
            elif decision == "ABORT" and status != TxStatus.ABORTED:
                print(f"\n[Coordinator] [Recovery] Found incomplete ABORT for TX {tx_id}")
                print(f"[Coordinator] [Recovery] Resuming Phase 2: ABORT...")
                
                # Similar logic for ABORT
                operations = tx_data.get("operations", {})
                for group in ["A", "B"]:
                    if group in operations or group in tx_data.get("participants", []):
                        group_nodes = self.group_a_nodes if group == "A" else self.group_b_nodes
                        leader = self.find_group_leader(group_nodes)
                        if leader:
                            node_id, host, port = leader
                            try:
                                print(f"[Coordinator] [Recovery] Sending ABORT to Group {group} (Node {node_id})")
                                proxy = self.get_connection(host, port)
                                if proxy:
                                    proxy.abort(tx_id)
                            except Exception as e:
                                print(f"[Coordinator] [Recovery] Error: {e}")
                
                self.tx_log[tx_id]["status"] = TxStatus.ABORTED
                self.save_tx_log()
                print(f"[Coordinator] [Recovery] TX {tx_id} ABORTED")
                recovered += 1
            
            # Case 3: PREPARED state with votes collected but no decision made yet
            elif status == TxStatus.PREPARED and decision is None:
                votes = tx_data.get("votes", {})
                all_commit = all(v == "VOTE_COMMIT" for v in votes.values()) if votes else False
                
                if all_commit and len(votes) == len(tx_data.get("participants", [])):
                    print(f"\n[Coordinator] [Recovery] Found PREPARED TX {tx_id} with all VOTE_COMMITs")
                    print(f"[Coordinator] [Recovery] Making decision: COMMIT")
                    tx_data["decision"] = "COMMIT"
                    self.save_tx_log()
                    # Recursively process this transaction
                    self.recover_incomplete_transactions()
                    return
                else:
                    print(f"\n[Coordinator] [Recovery] Found PREPARED TX {tx_id} without complete votes")
                    print(f"[Coordinator] [Recovery] Making decision: ABORT (safety)")
                    tx_data["decision"] = "ABORT"
                    self.save_tx_log()
                    self.recover_incomplete_transactions()
                    return
        
        if recovered > 0:
            print(f"\n[Coordinator] [Recovery] Recovered {recovered} incomplete transaction(s)")
        else:
            print(f"[Coordinator] [Recovery] No incomplete transactions found")
        print(f"[Coordinator] ========== RECOVERY COMPLETE ==========\n")

    def get_connection(self, host: str, port: int) -> Optional[RPCProxy]:
        """Get or create connection to a node"""
        key = (host, port)
        if key in self.connections:
            return self.connections[key]

        try:
            connection = Client((host, port), authkey=b'raft_cluster')
            proxy = RPCProxy(connection)
            self.connections[key] = proxy
            return proxy
        except Exception as e:
            print(f"[Coordinator] Failed to connect to {host}:{port}: {e}")
            return None

    def find_group_leader(self, group_nodes: List[tuple]) -> Optional[tuple]:
        """Find the leader of a participant group"""
        for node_id, host, port in group_nodes:
            try:
                proxy = self.get_connection(host, port)
                if proxy:
                    info = proxy.get_leader_info()
                    if info.get("is_leader"):
                        return (node_id, host, port)
                    elif info.get("leader_id") is not None:
                        # Find leader's connection info
                        leader_id = info["leader_id"]
                        for nid, h, p in group_nodes:
                            if nid == leader_id:
                                return (nid, h, p)
            except Exception as e:
                # Clear failed connection
                if (host, port) in self.connections:
                    del self.connections[(host, port)]
                continue
        return None

    def execute_transaction(self, operations: Dict[str, dict]) -> dict:
        """
        Execute a distributed transaction using 2PC

        operations: {
            "A": {"type": "debit/credit", "amount": 100},
            "B": {"type": "debit/credit", "amount": 100}
        }
        """
        tx_id = str(uuid.uuid4())[:8]
        print(f"\n{'='*70}")
        print(f"[Coordinator] Starting Transaction {tx_id}")
        print(f"[Coordinator] Operations: {operations}")
        print(f"{'='*70}")

        # Initialize transaction log
        with self.lock:
            self.tx_log[tx_id] = {
                "status": TxStatus.PENDING,
                "participants": list(operations.keys()),
                "operations": operations,
                "decision": None
            }
            self.save_tx_log()

        # Find leaders for each participant group
        leaders = {}
        if "A" in operations:
            leader_a = self.find_group_leader(self.group_a_nodes)
            if leader_a:
                leaders["A"] = leader_a
                print(f"[Coordinator] Group A leader: Node {leader_a[0]}")
            else:
                print(f"[Coordinator] ERROR: Cannot find Group A leader")
                return self._abort_transaction(tx_id, "Cannot find Group A leader")

        if "B" in operations:
            leader_b = self.find_group_leader(self.group_b_nodes)
            if leader_b:
                leaders["B"] = leader_b
                print(f"[Coordinator] Group B leader: Node {leader_b[0]}")
            else:
                print(f"[Coordinator] ERROR: Cannot find Group B leader")
                return self._abort_transaction(tx_id, "Cannot find Group B leader")

        # ==================== PHASE 1: PREPARE ====================
        print(f"\n[Coordinator] ========== PHASE 1: PREPARE ==========")

        with self.lock:
            self.tx_log[tx_id]["status"] = TxStatus.PREPARING
            self.save_tx_log()

        votes = {}
        for group, operation in operations.items():
            node_id, host, port = leaders[group]
            print(f"[Coordinator] Sending PREPARE to Group {group} (Node {node_id})")
            print(f"[Coordinator] Operation: {operation}")

            try:
                proxy = self.get_connection(host, port)
                if proxy:
                    # Send PREPARE request
                    response = proxy.prepare(tx_id, operation)

                    # Handle forwarding if we hit a non-leader
                    retry_count = 0
                    while response.get("vote") == "FORWARD" and retry_count < 3:
                        leader_id = response.get("leader_id")
                        print(f"[Coordinator] Forwarded to leader {leader_id}")
                        # Find new leader's connection
                        group_nodes = self.group_a_nodes if group == "A" else self.group_b_nodes
                        for nid, h, p in group_nodes:
                            if nid == leader_id:
                                proxy = self.get_connection(h, p)
                                if proxy:
                                    response = proxy.prepare(tx_id, operation)
                                break
                        retry_count += 1

                    votes[group] = response
                    vote = response.get("vote", "VOTE_ABORT")
                    reason = response.get("reason", "")

                    if vote == "VOTE_COMMIT":
                        print(f"[Coordinator] Group {group} voted: VOTE_COMMIT ✓")
                    else:
                        print(f"[Coordinator] Group {group} voted: VOTE_ABORT ✗ ({reason})")
                else:
                    votes[group] = {"vote": "VOTE_ABORT", "reason": "Connection failed"}
                    print(f"[Coordinator] Group {group}: Connection failed -> VOTE_ABORT")

            except Exception as e:
                votes[group] = {"vote": "VOTE_ABORT", "reason": str(e)}
                print(f"[Coordinator] Group {group}: Exception -> VOTE_ABORT ({e})")
                # Clear failed connection
                if (host, port) in self.connections:
                    del self.connections[(host, port)]

        # Check votes
        all_commit = all(v.get("vote") == "VOTE_COMMIT" for v in votes.values())

        with self.lock:
            self.tx_log[tx_id]["status"] = TxStatus.PREPARED
            self.tx_log[tx_id]["votes"] = {k: v.get("vote") for k, v in votes.items()}
            self.save_tx_log()

        # ==================== PHASE 2: COMMIT/ABORT ====================
        if all_commit:
            print(f"\n[Coordinator] ========== PHASE 2: COMMIT ==========")
            print(f"[Coordinator] All participants voted COMMIT -> Committing")
            
            # Check if crash demo mode is enabled
            if self.crash_demo_mode:
                print(f"\n" + "!" * 70)
                if self.crash_demo_mode == "1.c.ii":
                    print(f"!!! PAUSE FOR 1.c.ii CRASH DEMO (10 seconds) !!!")
                    print(f"!!! Go to PARTICIPANT LEADER terminal and press Ctrl+C NOW !!!")
                    print(f"!!! Participants are in PREPARED state !!!")
                    print(f"!!! After crash, Coordinator will still complete COMMIT !!!")
                elif self.crash_demo_mode == "1.c.iii":
                    print(f"!!! PAUSE FOR 1.c.iii CRASH DEMO (10 seconds) !!!")
                    print(f"!!! Press Ctrl+C on THIS COORDINATOR terminal NOW !!!")
                    print(f"!!! Participants are in PREPARED state, waiting for COMMIT !!!")
                else:
                    print(f"!!! CRASH DEMO PAUSE (10 seconds) !!!")
                print(f"!" * 70 + "\n")
                import time
                for i in range(10, 0, -1):
                    print(f"[Coordinator] Countdown: {i} seconds remaining...")
                    time.sleep(1)
                print(f"[Coordinator] Crash window closed, continuing with COMMIT...")
            
            return self._commit_transaction(tx_id, leaders, operations)
        else:
            print(f"\n[Coordinator] ========== PHASE 2: ABORT ==========")
            print(f"[Coordinator] Not all voted COMMIT -> Aborting")
            abort_reasons = [f"{k}: {v.get('reason', 'No vote')}" for k, v in votes.items() if v.get("vote") != "VOTE_COMMIT"]
            return self._abort_transaction(tx_id, "; ".join(abort_reasons), leaders, operations)

    def _commit_transaction(self, tx_id: str, leaders: Dict[str, tuple],
                           operations: Dict[str, dict]) -> dict:
        """Send COMMIT to all participants"""
        with self.lock:
            self.tx_log[tx_id]["status"] = TxStatus.COMMITTING
            self.tx_log[tx_id]["decision"] = "COMMIT"
            self.save_tx_log()

        results = {}
        for group in operations.keys():
            node_id, host, port = leaders[group]
            print(f"[Coordinator] Sending COMMIT to Group {group} (Node {node_id})")

            try:
                proxy = self.get_connection(host, port)
                if proxy:
                    response = proxy.commit(tx_id)
                    results[group] = response
                    balance = response.get("balance", "?")
                    print(f"[Coordinator] Group {group} COMMIT acknowledged. Balance: {balance}")
                else:
                    results[group] = {"success": False, "error": "Connection failed"}
            except Exception as e:
                results[group] = {"success": False, "error": str(e)}
                print(f"[Coordinator] Group {group} COMMIT error: {e}")

        with self.lock:
            self.tx_log[tx_id]["status"] = TxStatus.COMMITTED
            self.save_tx_log()

        print(f"\n[Coordinator] Transaction {tx_id} COMMITTED ✓")
        return {
            "tx_id": tx_id,
            "status": "COMMITTED",
            "results": results
        }

    def _abort_transaction(self, tx_id: str, reason: str,
                          leaders: Dict[str, tuple] = None,
                          operations: Dict[str, dict] = None) -> dict:
        """Send ABORT to all participants"""
        with self.lock:
            self.tx_log[tx_id]["status"] = TxStatus.ABORTING
            self.tx_log[tx_id]["decision"] = "ABORT"
            self.tx_log[tx_id]["abort_reason"] = reason
            self.save_tx_log()

        if leaders and operations:
            for group in operations.keys():
                if group in leaders:
                    node_id, host, port = leaders[group]
                    print(f"[Coordinator] Sending ABORT to Group {group} (Node {node_id})")

                    try:
                        proxy = self.get_connection(host, port)
                        if proxy:
                            response = proxy.abort(tx_id)
                            print(f"[Coordinator] Group {group} ABORT acknowledged")
                    except Exception as e:
                        print(f"[Coordinator] Group {group} ABORT error: {e}")

        with self.lock:
            self.tx_log[tx_id]["status"] = TxStatus.ABORTED
            self.save_tx_log()

        print(f"\n[Coordinator] Transaction {tx_id} ABORTED ✗")
        print(f"[Coordinator] Reason: {reason}")
        return {
            "tx_id": tx_id,
            "status": "ABORTED",
            "reason": reason
        }

    def get_transaction_status(self, tx_id: str) -> dict:
        """Get status of a transaction (for crash recovery)"""
        with self.lock:
            if tx_id in self.tx_log:
                tx = self.tx_log[tx_id]
                return {
                    "tx_id": tx_id,
                    "status": tx["status"].value if isinstance(tx["status"], TxStatus) else tx["status"],
                    "decision": tx.get("decision")
                }
            return {"tx_id": tx_id, "status": "UNKNOWN"}

    def get_status(self) -> dict:
        """Get coordinator status"""
        return {
            "node_id": self.node_id,
            "role": "coordinator",
            "active_transactions": len(self.tx_log),
            "group_a_nodes": len(self.group_a_nodes),
            "group_b_nodes": len(self.group_b_nodes)
        }

    def get_all_balances(self) -> dict:
        """Get current balances from both groups"""
        result = {"A": None, "B": None}

        # Get balance from Group A leader
        leader_a = self.find_group_leader(self.group_a_nodes)
        if leader_a:
            try:
                proxy = self.get_connection(leader_a[1], leader_a[2])
                if proxy:
                    balance_info = proxy.get_balance()
                    result["A"] = balance_info.get("balance")
            except:
                pass

        # Get balance from Group B leader
        leader_b = self.find_group_leader(self.group_b_nodes)
        if leader_b:
            try:
                proxy = self.get_connection(leader_b[1], leader_b[2])
                if proxy:
                    balance_info = proxy.get_balance()
                    result["B"] = balance_info.get("balance")
            except:
                pass

        return result

    def set_initial_balances(self, balance_a: float, balance_b: float) -> dict:
        """Set initial balances for testing scenarios"""
        results = {}

        # Set balance for Group A
        leader_a = self.find_group_leader(self.group_a_nodes)
        if leader_a:
            try:
                proxy = self.get_connection(leader_a[1], leader_a[2])
                if proxy:
                    result = proxy.set_initial_balance(balance_a)
                    results["A"] = result
                    print(f"[Coordinator] Group A initial balance set to {balance_a}")
            except Exception as e:
                results["A"] = {"error": str(e)}
        else:
            results["A"] = {"error": "No leader found"}

        # Set balance for Group B
        leader_b = self.find_group_leader(self.group_b_nodes)
        if leader_b:
            try:
                proxy = self.get_connection(leader_b[1], leader_b[2])
                if proxy:
                    result = proxy.set_initial_balance(balance_b)
                    results["B"] = result
                    print(f"[Coordinator] Group B initial balance set to {balance_b}")
            except Exception as e:
                results["B"] = {"error": str(e)}
        else:
            results["B"] = {"error": "No leader found"}

        return results

    # ==================== Crash Simulation ====================

    def simulate_crash_before_vote(self, delay: float = 30.0):
        """Simulate coordinator crash before collecting votes (for scenario 1.c.iii)"""
        print(f"[Coordinator] Will simulate crash (sleep {delay}s) during PREPARE phase")
        self.crash_during_prepare = True
        self.crash_delay = delay

    def simulate_participant_timeout(self, group: str, delay: float = 15.0):
        """Tell a participant to delay response (for scenario 1.c.i, 1.c.ii)"""
        group_nodes = self.group_a_nodes if group == "A" else self.group_b_nodes
        leader = self.find_group_leader(group_nodes)
        if leader:
            try:
                proxy = self.get_connection(leader[1], leader[2])
                if proxy:
                    # This would need corresponding method in participant
                    print(f"[Coordinator] Group {group} will simulate timeout ({delay}s)")
                    return {"success": True}
            except:
                pass
        return {"success": False}


# ==================== Transaction Helper Functions ====================

def transfer_100_from_a_to_b() -> Dict[str, dict]:
    """Transaction T1: Transfer $100 from A to B"""
    return {
        "A": {"type": "debit", "amount": 100},
        "B": {"type": "credit", "amount": 100}
    }


def bonus_20_percent_to_a_and_b(balance_a: float) -> Dict[str, dict]:
    """Transaction T2: Add 20% bonus to A and same amount to B"""
    bonus = balance_a * 0.2
    return {
        "A": {"type": "credit", "amount": bonus},
        "B": {"type": "credit", "amount": bonus}
    }
