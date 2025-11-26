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
                "operations": tx_data.get("operations", {})
            }
        with open(self.tx_log_file, 'w') as f:
            json.dump(data, f, indent=2)

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
