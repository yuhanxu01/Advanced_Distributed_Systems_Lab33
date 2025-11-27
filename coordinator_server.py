# -*- coding:utf-8 -*-
"""
CISC 6935 Distributed Systems - Lab 3
Coordinator Server - Run this on node1 (the 2PC coordinator)
"""

import pickle
import sys
import threading
import time
from multiprocessing.connection import Listener
from coordinator import Coordinator


class RPCHandler:
    """Handles RPC requests for Coordinator"""
    def __init__(self, coordinator: Coordinator):
        self.coordinator = coordinator
        self._functions = {}
        self._register_functions()

    def _register_functions(self):
        """Register all callable RPC functions"""
        self._functions['execute_transaction'] = self.coordinator.execute_transaction
        self._functions['get_status'] = self.coordinator.get_status
        self._functions['get_transaction_status'] = self.coordinator.get_transaction_status
        self._functions['get_all_balances'] = self.coordinator.get_all_balances
        self._functions['set_initial_balances'] = self.coordinator.set_initial_balances
        self._functions['enable_crash_demo'] = self.coordinator.enable_crash_demo

    def handle_connection(self, connection):
        """Handle incoming RPC connection"""
        try:
            while True:
                func_name, args, kwargs = pickle.loads(connection.recv())
                try:
                    result = self._functions[func_name](*args, **kwargs)
                    connection.send(pickle.dumps(result))
                except Exception as e:
                    print(f"[Coordinator RPC] Error: {e}")
                    connection.send(pickle.dumps({"error": str(e)}))
        except EOFError:
            pass


def rpc_server(handler: RPCHandler, address: tuple, authkey: bytes):
    """Start RPC server"""
    sock = Listener(address, authkey=authkey)
    print(f"[Coordinator RPC Server] Listening on {address[0]}:{address[1]}")

    while True:
        client = sock.accept()
        t = threading.Thread(target=handler.handle_connection, args=(client,))
        t.daemon = True
        t.start()


# ==================== Configuration ====================

# Coordinator runs on node1
COORDINATOR_IP = '10.128.0.2'
COORDINATOR_PORT = 5000

# Account A group (nodes 0, 2-5) - 5 nodes
GROUP_A_NODES = [
    (0, '10.128.0.5', 5000),   # node0
    (2, '10.128.0.3', 5000),   # node2
    (3, '10.128.0.4', 5000),   # node3
    (4, '10.128.0.6', 5000),   # node4
    (5, '10.128.0.8', 5000),   # node5
]

# Account B group (nodes 6-10) - 5 nodes
GROUP_B_NODES = [
    (6, '10.128.0.10', 5000),  # node6
    (7, '10.128.0.11', 5000),  # node7
    (8, '10.128.0.24', 5000),  # node8
    (9, '10.128.0.25', 5000),  # node9
    (10, '10.128.0.26', 5000), # node10
]


if __name__ == '__main__':
    print("=" * 60)
    print("Starting 2PC Coordinator (Node 1)")
    print(f"Listening on: 0.0.0.0:{COORDINATOR_PORT}")
    print(f"Group A nodes: {[n[0] for n in GROUP_A_NODES]}")
    print(f"Group B nodes: {[n[0] for n in GROUP_B_NODES]}")
    print("=" * 60)

    # Create coordinator
    coordinator = Coordinator(node_id=1, port=COORDINATOR_PORT)
    coordinator.set_participant_groups(GROUP_A_NODES, GROUP_B_NODES)
    
    # Load transaction log and recover any incomplete transactions
    coordinator.load_tx_log()
    coordinator.recover_incomplete_transactions()

    # Create RPC handler
    handler = RPCHandler(coordinator)

    # Start RPC server in background thread
    rpc_thread = threading.Thread(
        target=rpc_server,
        args=(handler, ('0.0.0.0', COORDINATOR_PORT), b'raft_cluster'),
        daemon=True
    )
    rpc_thread.start()

    print("[Coordinator] Server started. Waiting for connections...")
    print("[Coordinator] Client can connect to execute transactions.")

    # Keep main thread alive
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[Coordinator] Shutting down...")
