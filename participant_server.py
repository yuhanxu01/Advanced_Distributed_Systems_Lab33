# -*- coding:utf-8 -*-
"""
CISC 6935 Distributed Systems - Lab 3
Participant Server - Run this on each node in Account A or Account B groups
"""

import pickle
import sys
import threading
import time
from multiprocessing.connection import Listener
from participant_node import ParticipantNode


class RPCHandler:
    """Handles RPC requests for Participant node"""
    def __init__(self, participant: ParticipantNode):
        self.participant = participant
        self._functions = {}
        self._register_functions()

    def _register_functions(self):
        """Register all callable RPC functions"""
        # Raft RPCs
        self._functions['request_vote'] = self.participant.request_vote
        self._functions['append_entries'] = self.participant.append_entries

        # 2PC RPCs
        self._functions['prepare'] = self.participant.prepare
        self._functions['commit'] = self.participant.commit
        self._functions['abort'] = self.participant.abort

        # Status/Query RPCs
        self._functions['get_status'] = self.participant.get_status
        self._functions['get_leader_info'] = self.participant.get_leader_info
        self._functions['get_balance'] = self.participant.get_balance
        self._functions['set_initial_balance'] = self.participant.set_initial_balance
        self._functions['query_tx_status'] = self.participant.query_tx_status
        self._functions['enable_crash_demo'] = self.participant.enable_crash_demo

    def handle_connection(self, connection):
        """Handle incoming RPC connection"""
        try:
            while True:
                func_name, args, kwargs = pickle.loads(connection.recv())
                try:
                    result = self._functions[func_name](*args, **kwargs)
                    connection.send(pickle.dumps(result))
                except Exception as e:
                    connection.send(pickle.dumps(e))
        except EOFError:
            pass


def rpc_server(handler: RPCHandler, address: tuple, authkey: bytes):
    """Start RPC server"""
    sock = Listener(address, authkey=authkey)
    print(f"[RPC Server] Listening on {address[0]}:{address[1]}")

    while True:
        client = sock.accept()
        t = threading.Thread(target=handler.handle_connection, args=(client,))
        t.daemon = True
        t.start()


# ==================== Node Configurations ====================

# GCP Internal IPs for 11-node cluster
# node1 (10.128.0.2)  - Coordinator
# node0, node2-5      - Account A (5 nodes)
# node6-10            - Account B (5 nodes)

GROUP_A_CONFIG = {
    # (node_id, internal_ip, port)
    0: ('10.128.0.5', 5000),   # node0
    2: ('10.128.0.3', 5000),   # node2
    3: ('10.128.0.4', 5000),   # node3
    4: ('10.128.0.6', 5000),   # node4
    5: ('10.128.0.8', 5000),   # node5
}

GROUP_B_CONFIG = {
    6: ('10.128.0.10', 5000),  # node6
    7: ('10.128.0.11', 5000),  # node7
    8: ('10.128.0.24', 5000),  # node8
    9: ('10.128.0.25', 5000),  # node9
    10: ('10.128.0.26', 5000), # node10
}


def get_group_and_peers(node_id: int):
    """Determine which group this node belongs to and get peer list"""
    if node_id in GROUP_A_CONFIG:
        group_id = "A"
        my_ip, my_port = GROUP_A_CONFIG[node_id]
        peers = [(nid, ip, port) for nid, (ip, port) in GROUP_A_CONFIG.items() if nid != node_id]
    elif node_id in GROUP_B_CONFIG:
        group_id = "B"
        my_ip, my_port = GROUP_B_CONFIG[node_id]
        peers = [(nid, ip, port) for nid, (ip, port) in GROUP_B_CONFIG.items() if nid != node_id]
    else:
        raise ValueError(f"Node {node_id} is not configured as a participant (must be 2-10)")

    return group_id, my_ip, my_port, peers


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python participant_server.py <node_id> [--no-wait]")
        print("  node_id: 2-6 for Group A, 7-10 for Group B")
        print("  --no-wait: (optional) Start immediately without waiting for peers")
        sys.exit(1)

    node_id = int(sys.argv[1])
    wait_for_cluster = True

    if len(sys.argv) > 2 and sys.argv[2] == '--no-wait':
        wait_for_cluster = False
        print("⚠ Cluster synchronization disabled (--no-wait)")

    try:
        group_id, my_ip, my_port, peers = get_group_and_peers(node_id)
    except ValueError as e:
        print(e)
        sys.exit(1)

    print("=" * 60)
    print(f"Starting Participant Node {node_id} (Account {group_id})")
    print(f"This node: {my_ip}:{my_port}")
    print(f"Peers: {[(pid, ip) for pid, ip, _ in peers]}")
    if wait_for_cluster:
        print("Cluster sync: ENABLED")
    else:
        print("Cluster sync: DISABLED")
    print("=" * 60)

    # Create participant node
    participant = ParticipantNode(
        node_id=node_id,
        group_id=group_id,
        peers=peers,
        port=my_port,
        initial_balance=0.0,
        wait_for_cluster=wait_for_cluster
    )
    participant.run()

    # Create RPC handler
    handler = RPCHandler(participant)

    # Start RPC server in background thread
    print(f"[Node {node_id}] Starting RPC server on 0.0.0.0:{my_port}")
    rpc_thread = threading.Thread(
        target=rpc_server,
        args=(handler, ('0.0.0.0', my_port), b'raft_cluster'),
        daemon=True
    )
    rpc_thread.start()

    # Small delay to ensure RPC server is listening
    time.sleep(0.5)

    # Start cluster synchronization and election timers
    participant.start_cluster_sync()

    # Keep main thread alive
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print(f"\n[Node {node_id}] Shutting down...")
        participant.stop()
