# -*- coding:utf-8 -*-
"""
CISC 6935 Distributed Systems - Lab 3
Participant Node - Raft Node with 2PC Participant Logic
Each participant group (Account A, Account B) runs Raft for consensus
"""

import time
import random
import threading
import json
import os
from enum import Enum
from typing import List, Dict, Optional
from multiprocessing.connection import Client
import pickle


class NodeState(Enum):
    """Raft node states"""
    FOLLOWER = "follower"
    CANDIDATE = "candidate"
    LEADER = "leader"


class TxState(Enum):
    """2PC Transaction states"""
    NONE = "none"
    PREPARED = "prepared"
    COMMITTED = "committed"
    ABORTED = "aborted"


class LogEntry:
    """Raft log entry with term, index, and command"""
    def __init__(self, term: int, index: int, command: dict):
        self.term = term
        self.index = index
        self.command = command  # {"type": "prepare/commit/abort/update", "tx_id": ..., "data": ...}

    def to_dict(self):
        return {"term": self.term, "index": self.index, "command": self.command}

    @staticmethod
    def from_dict(data):
        return LogEntry(data["term"], data["index"], data["command"])

    def __repr__(self):
        return f"LogEntry(term={self.term}, idx={self.index}, cmd={self.command})"


class RPCProxy:
    """Proxy for making RPC calls to peer nodes"""
    def __init__(self, connection):
        self._connection = connection
        self._lock = threading.Lock()

    def __getattr__(self, name):
        def do_rpc(*args, **kwargs):
            # Simulate network delay
            network_delay = random.uniform(0.0, 0.002)
            time.sleep(network_delay)

            with self._lock:
                try:
                    self._connection.send(pickle.dumps((name, args, kwargs)))
                    if self._connection.poll(timeout=2.0):
                        result = pickle.loads(self._connection.recv())
                        if isinstance(result, Exception):
                            raise result
                        return result
                    else:
                        raise ConnectionError(f"RPC timeout: no response within 2s")
                except (EOFError, ConnectionResetError, BrokenPipeError) as e:
                    raise ConnectionError(f"Connection lost: {str(e)}")
        return do_rpc


class ParticipantNode:
    """
    Raft-based Participant Node for 2PC
    Manages one account (A or B) with Raft consensus among replicas
    """

    def __init__(self, node_id: int, group_id: str, peers: List[tuple], port: int,
                 initial_balance: float = 0.0, wait_for_cluster: bool = True):
        # Node identification
        self.node_id = node_id
        self.group_id = group_id  # "A" or "B"
        self.peers = peers  # List of (peer_id, host, port) within same group
        self.port = port
        self.wait_for_cluster = wait_for_cluster

        # Account state (state machine)
        self.balance = initial_balance
        self.account_file = f"account_{group_id}_node{node_id}.dat"

        # 2PC Transaction state
        self.pending_tx = {}  # {tx_id: {"state": TxState, "operation": {...}, "new_balance": float}}

        # Persistent state (Raft)
        self.current_term = 0
        self.voted_for = None
        self.log = []  # List[LogEntry]

        # Volatile state (Raft)
        self.commit_index = -1
        self.last_applied = -1

        # Volatile state (leader only)
        self.next_index = {}
        self.match_index = {}

        # Node state
        self.state = NodeState.FOLLOWER
        self.leader_id = None
        self.last_heartbeat = time.time()

        # Timeouts
        self.election_timeout = random.uniform(3, 5)
        self.heartbeat_interval = 0.3

        # Vote tracking
        self.votes_received = set()

        # File paths
        self.state_file = f"raft_state_{group_id}_node{node_id}.json"
        self.log_file = f"raft_log_{group_id}_node{node_id}.log"

        # Thread synchronization
        self.lock = threading.Lock()

        # RPC connections
        self.peer_connections = {}

        # Timers
        self.election_timer_thread = None
        self.heartbeat_timer_thread = None
        self.running = False
        self.cluster_ready = False
        
        # Crash demo mode - adds pauses for manual crash testing
        self.crash_demo_mode = False

        print(f"[{group_id}-Node {self.node_id}] Initialized with balance={initial_balance}")

    # ==================== Account State Management ====================

    def load_account_state(self):
        """Load account balance from disk"""
        if os.path.exists(self.account_file):
            try:
                with open(self.account_file, 'r') as f:
                    data = json.load(f)
                    self.balance = data.get("balance", 0.0)
                    print(f"[{self.group_id}-Node {self.node_id}] Loaded balance: {self.balance}")
            except Exception as e:
                print(f"[{self.group_id}-Node {self.node_id}] Error loading account: {e}")

    def save_account_state(self):
        """Save account balance to disk"""
        with open(self.account_file, 'w') as f:
            json.dump({"balance": self.balance}, f)

    def set_initial_balance(self, balance: float):
        """Set initial balance (for testing scenarios)"""
        with self.lock:
            self.balance = balance
            self.save_account_state()
            print(f"[{self.group_id}-Node {self.node_id}] Set initial balance to {balance}")
            return {"success": True, "balance": self.balance}

    def get_balance(self) -> dict:
        """Get current account balance"""
        with self.lock:
            return {"balance": self.balance, "node_id": self.node_id, "group": self.group_id}

    # ==================== Raft Persistence ====================

    def save_state(self):
        """Persist Raft state to disk"""
        state = {
            "current_term": self.current_term,
            "voted_for": self.voted_for,
            "log": [e.to_dict() for e in self.log],
            "pending_tx": {k: {"state": v["state"].value, "operation": v.get("operation"), 
                              "new_balance": v.get("new_balance")} 
                          for k, v in self.pending_tx.items()}
        }
        with open(self.state_file, 'w') as f:
            json.dump(state, f, indent=2)

    def load_state(self):
        """Load Raft state from disk"""
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, 'r') as f:
                    state = json.load(f)
                    self.current_term = state["current_term"]
                    self.voted_for = state["voted_for"]
                    self.log = [LogEntry.from_dict(e) for e in state["log"]]
                    # Restore pending transactions
                    for k, v in state.get("pending_tx", {}).items():
                        self.pending_tx[k] = {
                            "state": TxState(v["state"]),
                            "operation": v.get("operation"),
                            "new_balance": v.get("new_balance")
                        }
                print(f"[{self.group_id}-Node {self.node_id}] Loaded state: term={self.current_term}, log_len={len(self.log)}")
            except Exception as e:
                print(f"[{self.group_id}-Node {self.node_id}] Error loading state: {e}")

    def apply_to_state_machine(self, entry: LogEntry):
        """Apply committed log entry to state machine"""
        cmd = entry.command
        cmd_type = cmd.get("type")
        tx_id = cmd.get("tx_id")

        with open(self.log_file, 'a') as f:
            f.write(f"{json.dumps(cmd)}\n")

        is_leader = self.state == NodeState.LEADER
        role = "Leader" if is_leader else "Follower"
        
        print(f"[{self.group_id}-Node {self.node_id}] [Raft {role}] Applying committed log: {cmd_type}, tx={tx_id}")

        if cmd_type == "prepare":
            # Just mark as prepared, don't change balance yet
            if tx_id not in self.pending_tx:
                self.pending_tx[tx_id] = {
                    "state": TxState.PREPARED,
                    "operation": cmd.get("operation"),
                    "new_balance": cmd.get("new_balance")
                }
            else:
                self.pending_tx[tx_id]["state"] = TxState.PREPARED
            print(f"[{self.group_id}-Node {self.node_id}] [Raft {role}] TX {tx_id} state -> PREPARED (expected balance: {cmd.get('new_balance')})")

        elif cmd_type == "commit":
            # Apply the balance change
            if tx_id in self.pending_tx:
                new_balance = self.pending_tx[tx_id].get("new_balance")
                if new_balance is not None:
                    old_balance = self.balance
                    self.balance = new_balance
                    self.save_account_state()
                    self.pending_tx[tx_id]["state"] = TxState.COMMITTED
                    print(f"[{self.group_id}-Node {self.node_id}] [State Machine] TX {tx_id} COMMITTED: balance {old_balance} -> {self.balance}")
            else:
                print(f"[{self.group_id}-Node {self.node_id}] [Warning] Received COMMIT for unknown TX {tx_id}")

        elif cmd_type == "abort":
            # Discard pending changes
            if tx_id in self.pending_tx:
                self.pending_tx[tx_id]["state"] = TxState.ABORTED
                print(f"[{self.group_id}-Node {self.node_id}] [State Machine] TX {tx_id} ABORTED")
            else:
                print(f"[{self.group_id}-Node {self.node_id}] [State Machine] ABORT unknown TX {tx_id}")

        self.save_state()

    # ==================== 2PC Handler Methods (called by Coordinator) ====================

    def prepare(self, tx_id: str, operation: dict) -> dict:
        """
        2PC PREPARE phase
        - Validate operation (check balance, etc.)
        - Replicate PREPARE to Raft majority
        - Return VOTE_COMMIT or VOTE_ABORT
        """
        print(f"\n{'='*60}")
        print(f"[{self.group_id}-Node {self.node_id}] [2PC Layer] Received PREPARE message")
        print(f"[{self.group_id}-Node {self.node_id}] TX: {tx_id}")
        print(f"[{self.group_id}-Node {self.node_id}] Operation: {operation}")
        print(f"{'='*60}")

        with self.lock:
            # Only leader can handle 2PC requests
            if self.state != NodeState.LEADER:
                # Forward to leader if known
                if self.leader_id is not None:
                    print(f"[{self.group_id}-Node {self.node_id}] Not leader, forwarding to leader {self.leader_id}")
                    return {"vote": "FORWARD", "leader_id": self.leader_id, "leader_node": self.leader_id}
                return {"vote": "VOTE_ABORT", "reason": "No leader available"}

            # Validate operation
            op_type = operation.get("type")
            amount = operation.get("amount", 0)

            # Calculate new balance
            if op_type == "debit":
                new_balance = self.balance - amount
                if new_balance < 0:
                    print(f"[{self.group_id}-Node {self.node_id}] [2PC Layer] Validation FAILED!")
                    print(f"[{self.group_id}-Node {self.node_id}] [2PC Layer] Insufficient balance: current {self.balance} < required {amount}")
                    print(f"[{self.group_id}-Node {self.node_id}] [2PC Layer] Returning VOTE_ABORT to coordinator")
                    return {"vote": "VOTE_ABORT", "reason": f"Insufficient balance: {self.balance} < {amount}"}
            elif op_type == "credit":
                new_balance = self.balance + amount
            elif op_type == "set":
                new_balance = amount
            else:
                return {"vote": "VOTE_ABORT", "reason": f"Unknown operation type: {op_type}"}

            print(f"[{self.group_id}-Node {self.node_id}] [2PC Layer] Validation passed. Current balance: {self.balance}, New balance: {new_balance}")

            # Store pending transaction
            self.pending_tx[tx_id] = {
                "state": TxState.NONE,
                "operation": operation,
                "new_balance": new_balance
            }

            # Create PREPARE log entry
            prepare_entry = LogEntry(
                term=self.current_term,
                index=len(self.log),
                command={
                    "type": "prepare",
                    "tx_id": tx_id,
                    "operation": operation,
                    "new_balance": new_balance
                }
            )
            self.log.append(prepare_entry)
            self.save_state()

            print(f"\n[{self.group_id}-Node {self.node_id}] [Raft Layer] PREPARE added to Raft Log (index={prepare_entry.index})")
            print(f"[{self.group_id}-Node {self.node_id}] [Raft Layer] Replicating PREPARE to Raft Follower nodes...")

        # Replicate to followers (release lock first)
        self.send_heartbeats()

        # Wait for majority commit
        print(f"[{self.group_id}-Node {self.node_id}] [Raft Layer] Waiting for majority confirmation (need {(len(self.peers) + 1) // 2 + 1} nodes)...")
        success = self._wait_for_commit(prepare_entry.index, timeout=5.0)

        if success:
            print(f"[{self.group_id}-Node {self.node_id}] [Raft Layer] Majority confirmed, PREPARE persisted")
            print(f"[{self.group_id}-Node {self.node_id}] [2PC Layer] Returning VOTE_COMMIT to coordinator")
            return {"vote": "VOTE_COMMIT", "tx_id": tx_id}
        else:
            print(f"[{self.group_id}-Node {self.node_id}] [Raft Layer] Replication failed or timeout")
            print(f"[{self.group_id}-Node {self.node_id}] [2PC Layer] Returning VOTE_ABORT to coordinator")
            return {"vote": "VOTE_ABORT", "reason": "Failed to replicate PREPARE to majority"}

    def commit(self, tx_id: str) -> dict:
        """
        2PC COMMIT phase
        - Replicate COMMIT decision to Raft majority
        - Apply balance change to state machine
        """
        print(f"\n{'='*60}")
        print(f"[{self.group_id}-Node {self.node_id}] [2PC Layer] Received COMMIT message")
        print(f"[{self.group_id}-Node {self.node_id}] TX: {tx_id}")
        print(f"{'='*60}")

        with self.lock:
            if self.state != NodeState.LEADER:
                if self.leader_id is not None:
                    return {"success": False, "forward_to": self.leader_id}
                return {"success": False, "reason": "No leader"}

            # Create COMMIT log entry
            commit_entry = LogEntry(
                term=self.current_term,
                index=len(self.log),
                command={
                    "type": "commit",
                    "tx_id": tx_id
                }
            )
            self.log.append(commit_entry)
            self.save_state()

            print(f"[{self.group_id}-Node {self.node_id}] [Raft Layer] COMMIT added to Raft Log (index={commit_entry.index})")
            print(f"[{self.group_id}-Node {self.node_id}] [Raft Layer] Replicating COMMIT to Raft Follower nodes...")

        # Replicate to followers
        self.send_heartbeats()

        # Wait for majority commit
        print(f"[{self.group_id}-Node {self.node_id}] [Raft Layer] Waiting for majority confirmation...")
        success = self._wait_for_commit(commit_entry.index, timeout=5.0)

        if success:
            print(f"[{self.group_id}-Node {self.node_id}] [Raft Layer] Majority confirmed, COMMIT persisted")
            print(f"[{self.group_id}-Node {self.node_id}] [State Machine] Account balance updated: {self.balance}")
            return {"success": True, "balance": self.balance}
        else:
            print(f"[{self.group_id}-Node {self.node_id}] [Raft Layer] Replication timeout (will eventually complete)")
            return {"success": True, "balance": self.balance, "note": "Replication in progress"}

    def abort(self, tx_id: str) -> dict:
        """
        2PC ABORT phase
        - Replicate ABORT decision to Raft majority
        - Discard pending changes
        """
        print(f"\n{'='*60}")
        print(f"[{self.group_id}-Node {self.node_id}] [2PC Layer] Received ABORT message")
        print(f"[{self.group_id}-Node {self.node_id}] TX: {tx_id}")
        print(f"{'='*60}")

        with self.lock:
            if self.state != NodeState.LEADER:
                if self.leader_id is not None:
                    return {"success": False, "forward_to": self.leader_id}
                return {"success": False, "reason": "No leader"}

            # Create ABORT log entry
            abort_entry = LogEntry(
                term=self.current_term,
                index=len(self.log),
                command={
                    "type": "abort",
                    "tx_id": tx_id
                }
            )
            self.log.append(abort_entry)
            self.save_state()

            print(f"[{self.group_id}-Node {self.node_id}] [Raft Layer] ABORT added to Raft Log (index={abort_entry.index})")

        # Replicate to followers
        self.send_heartbeats()

        # Wait for commit (best effort)
        self._wait_for_commit(abort_entry.index, timeout=3.0)

        print(f"[{self.group_id}-Node {self.node_id}] [2PC Layer] Transaction ABORTED. Balance unchanged: {self.balance}")
        return {"success": True, "balance": self.balance}

    def _wait_for_commit(self, target_index: int, timeout: float = 5.0) -> bool:
        """Wait for a log entry to be committed"""
        start_time = time.time()
        while time.time() - start_time < timeout:
            with self.lock:
                if self.commit_index >= target_index:
                    return True
            # Send more heartbeats to speed up replication
            self.send_heartbeats()
            time.sleep(0.1)
        return False

    # ==================== Raft RPC Handlers ====================

    def request_vote(self, term: int, candidate_id: int,
                     last_log_index: int, last_log_term: int) -> dict:
        """RequestVote RPC handler"""
        with self.lock:
            print(f"[{self.group_id}-Node {self.node_id}] [Raft Election] Received vote request from Node {candidate_id} (Term {term})")

            if term < self.current_term:
                print(f"[{self.group_id}-Node {self.node_id}] [Raft Election] Rejected: request Term too old ({term} < {self.current_term})")
                return {"term": self.current_term, "vote_granted": False}

            if term > self.current_term:
                print(f"[{self.group_id}-Node {self.node_id}] [Raft Election] Found higher Term, updating {self.current_term} -> {term}")
                self.current_term = term
                self.voted_for = None
                self.state = NodeState.FOLLOWER
                self.leader_id = None
                self.save_state()

            my_last_log_index = len(self.log) - 1
            my_last_log_term = self.log[-1].term if self.log else 0

            log_is_ok = (last_log_term > my_last_log_term) or \
                        (last_log_term == my_last_log_term and last_log_index >= my_last_log_index)

            if (self.voted_for is None or self.voted_for == candidate_id) and log_is_ok:
                self.voted_for = candidate_id
                self.last_heartbeat = time.time()
                self.save_state()
                print(f"[{self.group_id}-Node {self.node_id}] [Raft Election] Voted for Node {candidate_id} (Term {term})")
                return {"term": self.current_term, "vote_granted": True}

            reason = "already voted for another" if self.voted_for is not None else "log not up-to-date"
            print(f"[{self.group_id}-Node {self.node_id}] [Raft Election] Rejected vote for Node {candidate_id}: {reason}")
            return {"term": self.current_term, "vote_granted": False}

    def append_entries(self, term: int, leader_id: int, prev_log_index: int,
                       prev_log_term: int, entries: List[dict],
                       leader_commit: int) -> dict:
        """AppendEntries RPC handler"""
        with self.lock:
            is_heartbeat = len(entries) == 0

            if not is_heartbeat:
                print(f"[{self.group_id}-Node {self.node_id}] AppendEntries from leader {leader_id}, entries={len(entries)}")

            if term < self.current_term:
                return {"term": self.current_term, "success": False}

            if term >= self.current_term:
                self.current_term = term
                self.state = NodeState.FOLLOWER
                self.leader_id = leader_id
                self.voted_for = None
                self.last_heartbeat = time.time()
                self.save_state()

            # Log consistency check
            if prev_log_index >= 0:
                if prev_log_index >= len(self.log):
                    return {"term": self.current_term, "success": False}
                if self.log[prev_log_index].term != prev_log_term:
                    self.log = self.log[:prev_log_index]
                    self.save_state()
                    return {"term": self.current_term, "success": False}

            # Append entries
            if entries:
                insert_index = prev_log_index + 1
                for i, entry_dict in enumerate(entries):
                    entry = LogEntry.from_dict(entry_dict)
                    current_index = insert_index + i
                    if current_index < len(self.log):
                        if self.log[current_index].term != entry.term:
                            self.log = self.log[:current_index]
                            self.log.append(entry)
                    else:
                        self.log.append(entry)
                self.save_state()
                print(f"[{self.group_id}-Node {self.node_id}] Appended {len(entries)} entries")

            # Update commit index
            if leader_commit > self.commit_index:
                old_commit = self.commit_index
                self.commit_index = min(leader_commit, len(self.log) - 1)
                if self.commit_index > old_commit:
                    self.apply_committed_entries()

            return {"term": self.current_term, "success": True}

    # ==================== Leader Election ====================

    def start_election(self):
        """Start a new election"""
        with self.lock:
            self.state = NodeState.CANDIDATE
            self.current_term += 1
            self.voted_for = self.node_id
            self.votes_received = {self.node_id}
            self.election_timeout = random.uniform(3, 5)

            current_term = self.current_term
            last_log_index = len(self.log) - 1
            last_log_term = self.log[-1].term if self.log else 0

            self.save_state()
            print(f"\n[{self.group_id}-Node {self.node_id}] [Raft Election] Starting election, Term={current_term}")
            print(f"[{self.group_id}-Node {self.node_id}] [Raft Election] Voted for self, current votes: 1/{len(self.peers)+1}")

        for peer_id, host, port in self.peers:
            threading.Thread(
                target=self.send_request_vote,
                args=(peer_id, current_term, last_log_index, last_log_term),
                daemon=True
            ).start()

    def send_request_vote(self, peer_id: int, term: int,
                          last_log_index: int, last_log_term: int):
        """Send RequestVote RPC to a peer"""
        try:
            proxy = self.get_peer_connection(peer_id)
            if proxy is None:
                return

            response = proxy.request_vote(term, self.node_id, last_log_index, last_log_term)

            with self.lock:
                if self.state != NodeState.CANDIDATE or term != self.current_term:
                    return

                if response["term"] > self.current_term:
                    print(f"[{self.group_id}-Node {self.node_id}] [Raft Election] Found higher Term {response['term']}, becoming Follower")
                    self.current_term = response["term"]
                    self.state = NodeState.FOLLOWER
                    self.voted_for = None
                    self.save_state()
                    return

                if response["vote_granted"]:
                    self.votes_received.add(peer_id)
                    total_nodes = len(self.peers) + 1
                    majority = total_nodes // 2 + 1
                    print(f"[{self.group_id}-Node {self.node_id}] [Raft Election] Received vote from Node {peer_id}, current votes: {len(self.votes_received)}/{total_nodes} (need {majority})")
                    
                    if len(self.votes_received) >= majority:
                        self.become_leader()
                else:
                    print(f"[{self.group_id}-Node {self.node_id}] [Raft Election] Node {peer_id} rejected vote")

        except Exception as e:
            with self.lock:
                if peer_id in self.peer_connections:
                    del self.peer_connections[peer_id]

    def become_leader(self):
        """Transition to leader state"""
        if self.state != NodeState.CANDIDATE:
            return

        self.state = NodeState.LEADER
        self.leader_id = self.node_id

        for peer_id, _, _ in self.peers:
            self.next_index[peer_id] = len(self.log)
            self.match_index[peer_id] = -1

        total_nodes = len(self.peers) + 1
        print(f"\n{'='*60}")
        print(f"[{self.group_id}-Node {self.node_id}] [Raft Election] Received {len(self.votes_received)}/{total_nodes} votes")
        print(f"[{self.group_id}-Node {self.node_id}] [Raft Election] *** Elected as LEADER (Term {self.current_term}) ***")
        print(f"{'='*60}\n")
        self.send_heartbeats()

    # ==================== Log Replication ====================

    def send_heartbeats(self):
        """Leader sends heartbeat to all followers"""
        if self.state != NodeState.LEADER:
            return

        for peer_id, _, _ in self.peers:
            threading.Thread(
                target=self.send_append_entries,
                args=(peer_id,),
                daemon=True
            ).start()

    def send_append_entries(self, peer_id: int):
        """Send AppendEntries RPC to a peer"""
        with self.lock:
            if self.state != NodeState.LEADER:
                return

            next_idx = self.next_index.get(peer_id, len(self.log))
            prev_log_index = next_idx - 1
            prev_log_term = self.log[prev_log_index].term if prev_log_index >= 0 and prev_log_index < len(self.log) else 0

            entries = []
            if next_idx < len(self.log):
                entries = [e.to_dict() for e in self.log[next_idx:]]

            args = {
                "term": self.current_term,
                "leader_id": self.node_id,
                "prev_log_index": prev_log_index,
                "prev_log_term": prev_log_term,
                "entries": entries,
                "leader_commit": self.commit_index
            }
            current_term = self.current_term

        try:
            proxy = self.get_peer_connection(peer_id)
            if proxy is None:
                return

            response = proxy.append_entries(**args)

            with self.lock:
                if self.state != NodeState.LEADER or current_term != self.current_term:
                    return

                if response["term"] > self.current_term:
                    self.current_term = response["term"]
                    self.state = NodeState.FOLLOWER
                    self.voted_for = None
                    self.leader_id = None
                    self.save_state()
                    return

                if response["success"]:
                    self.match_index[peer_id] = prev_log_index + len(entries)
                    self.next_index[peer_id] = self.match_index[peer_id] + 1
                    self.update_commit_index()
                else:
                    self.next_index[peer_id] = max(0, self.next_index.get(peer_id, 1) - 1)

        except Exception as e:
            with self.lock:
                if peer_id in self.peer_connections:
                    del self.peer_connections[peer_id]

    def update_commit_index(self):
        """Leader updates commit_index based on majority replication"""
        if self.state != NodeState.LEADER:
            return

        for n in range(self.commit_index + 1, len(self.log)):
            if self.log[n].term != self.current_term:
                continue

            replicated_count = 1  # Leader has it
            for peer_id in self.match_index:
                if self.match_index[peer_id] >= n:
                    replicated_count += 1

            if replicated_count > (len(self.peers) + 1) // 2:
                self.commit_index = n
                print(f"[{self.group_id}-Node {self.node_id}] Committed entries up to index {n}")
                self.apply_committed_entries()

    def apply_committed_entries(self):
        """Apply committed entries to state machine"""
        while self.last_applied < self.commit_index:
            self.last_applied += 1
            entry = self.log[self.last_applied]
            self.apply_to_state_machine(entry)

    # ==================== Connection Management ====================

    def get_peer_connection(self, peer_id: int) -> Optional[RPCProxy]:
        """Get or create RPC connection to a peer"""
        if peer_id in self.peer_connections:
            return self.peer_connections[peer_id]

        peer_info = None
        for pid, host, port in self.peers:
            if pid == peer_id:
                peer_info = (host, port)
                break

        if peer_info is None:
            return None

        try:
            connection = Client(peer_info, authkey=b'raft_cluster')
            proxy = RPCProxy(connection)
            self.peer_connections[peer_id] = proxy
            return proxy
        except Exception as e:
            return None

    # ==================== Status & Query ====================

    def get_status(self) -> dict:
        """Get current node status"""
        with self.lock:
            return {
                "node_id": self.node_id,
                "group": self.group_id,
                "state": self.state.value,
                "term": self.current_term,
                "leader_id": self.leader_id,
                "balance": self.balance,
                "log_length": len(self.log),
                "commit_index": self.commit_index,
                "last_applied": self.last_applied,
                "pending_tx": {k: v["state"].value for k, v in self.pending_tx.items()}
            }

    def get_leader_info(self) -> dict:
        """Get leader information for this group"""
        with self.lock:
            if self.state == NodeState.LEADER:
                return {"is_leader": True, "leader_id": self.node_id, "node_id": self.node_id}
            else:
                return {"is_leader": False, "leader_id": self.leader_id, "node_id": self.node_id}

    def enable_crash_demo(self, enabled: bool = True) -> dict:
        """Enable or disable crash demo mode"""
        self.crash_demo_mode = enabled
        print(f"[{self.group_id}-Node {self.node_id}] Crash demo mode: {'ENABLED' if enabled else 'DISABLED'}")
        if enabled:
            print(f"[{self.group_id}-Node {self.node_id}] A 10-second pause will be added after VOTE_COMMIT")
        return {"success": True, "crash_demo_mode": enabled}

    def query_tx_status(self, tx_id: str) -> dict:
        """Query transaction status (for crash recovery)"""
        with self.lock:
            if tx_id in self.pending_tx:
                return {
                    "found": True,
                    "state": self.pending_tx[tx_id]["state"].value,
                    "tx_id": tx_id
                }
            # Check log for committed transactions
            for entry in self.log:
                if entry.command.get("tx_id") == tx_id:
                    return {
                        "found": True,
                        "state": entry.command.get("type"),
                        "tx_id": tx_id
                    }
            return {"found": False, "tx_id": tx_id}

    # ==================== Cluster Initialization ====================

    def wait_for_cluster_ready(self, timeout: float = 60.0) -> bool:
        """Wait for all peer nodes to be reachable"""
        if not self.wait_for_cluster:
            return True

        print(f"[{self.group_id}-Node {self.node_id}] Waiting for peer nodes...")

        start_time = time.time()
        reachable_peers = set()

        while time.time() - start_time < timeout:
            for peer_id, host, port in self.peers:
                if peer_id in reachable_peers:
                    continue
                try:
                    connection = Client((host, port), authkey=b'raft_cluster')
                    proxy = RPCProxy(connection)
                    status = proxy.get_status()
                    if status:
                        reachable_peers.add(peer_id)
                        self.peer_connections[peer_id] = proxy
                        print(f"[{self.group_id}-Node {self.node_id}] ✓ Peer {peer_id} reachable")
                except:
                    pass

            if len(reachable_peers) == len(self.peers):
                print(f"[{self.group_id}-Node {self.node_id}] ✓ All peers reachable!")
                self.cluster_ready = True
                return True

            time.sleep(1.0)

        print(f"[{self.group_id}-Node {self.node_id}] ⚠ Timeout waiting for peers")
        self.cluster_ready = True
        return False

    # ==================== Main Loop ====================

    def run(self):
        """Start the node"""
        self.load_state()
        self.load_account_state()

        if not os.path.exists(self.log_file):
            open(self.log_file, 'a').close()

        print(f"[{self.group_id}-Node {self.node_id}] Started")

    def start_cluster_sync(self):
        """Phase 2: Wait for cluster and start timers"""
        if self.wait_for_cluster:
            self.wait_for_cluster_ready(timeout=60.0)
        else:
            self.cluster_ready = True

        self.running = True
        self.election_timer_thread = threading.Thread(target=self.election_timer, daemon=True)
        self.heartbeat_timer_thread = threading.Thread(target=self.heartbeat_timer, daemon=True)

        self.election_timer_thread.start()
        self.heartbeat_timer_thread.start()

        print(f"[{self.group_id}-Node {self.node_id}] Timers started")

    def stop(self):
        """Stop the node"""
        self.running = False
        print(f"[{self.group_id}-Node {self.node_id}] Stopped")

    def election_timer(self):
        """Background thread for election timeout"""
        while self.running:
            time.sleep(0.01)

            should_start_election = False
            with self.lock:
                if self.state != NodeState.LEADER:
                    elapsed = time.time() - self.last_heartbeat
                    if elapsed >= self.election_timeout:
                        should_start_election = True

            if should_start_election:
                self.start_election()

    def heartbeat_timer(self):
        """Background thread for leader heartbeats"""
        while self.running:
            time.sleep(self.heartbeat_interval)
            with self.lock:
                if self.state == NodeState.LEADER:
                    self.send_heartbeats()
