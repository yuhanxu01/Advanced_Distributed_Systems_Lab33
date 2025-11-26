#!/bin/bash
# Cleanup script for Lab 3: 2PC + Raft
# Removes all persistent state files to start fresh

echo "=================================================="
echo "Lab 3: 2PC + Raft - Cleanup Script"
echo "=================================================="
echo ""
echo "This script will remove all persistent state files:"
echo "  - raft_state_*.json (Raft persistent state)"
echo "  - raft_log_*.log (Raft log files)"
echo "  - account_*.dat (Account balance files)"
echo "  - coordinator_tx_log.json (Coordinator transaction log)"
echo ""
echo "⚠ WARNING: This will delete all state data!"
echo ""
read -p "Continue? (y/n): " -n 1 -r
echo

if [[ $REPLY =~ ^[Yy]$ ]]
then
    echo ""
    echo "Removing state files..."

    # Remove Raft state files
    rm -f raft_state_*.json
    echo "  ✓ Removed raft_state_*.json"

    # Remove Raft log files
    rm -f raft_log_*.log
    echo "  ✓ Removed raft_log_*.log"

    # Remove account balance files
    rm -f account_*.dat
    echo "  ✓ Removed account_*.dat"

    # Remove coordinator transaction log
    rm -f coordinator_tx_log.json
    echo "  ✓ Removed coordinator_tx_log.json"

    echo ""
    echo "✓ Cleanup completed!"
    echo ""
    echo "Next steps:"
    echo ""
    echo "  1. On node1 (Coordinator):"
    echo "     python3 coordinator_server.py"
    echo ""
    echo "  2. On nodes 0, 2-5 (Account A - 5 nodes):"
    echo "     python3 participant_server.py 0   # node0"
    echo "     python3 participant_server.py 2   # node2"
    echo "     python3 participant_server.py 3   # node3"
    echo "     python3 participant_server.py 4   # node4"
    echo "     python3 participant_server.py 5   # node5"
    echo ""
    echo "  3. On nodes 6-10 (Account B - 5 nodes):"
    echo "     python3 participant_server.py 6   # node6"
    echo "     python3 participant_server.py 7   # node7"
    echo "     python3 participant_server.py 8   # node8"
    echo "     python3 participant_server.py 9   # node9"
    echo "     python3 participant_server.py 10  # node10"
    echo ""
    echo "  4. Run client from any machine:"
    echo "     python3 client.py"
    echo ""
else
    echo ""
    echo "Cleanup cancelled."
fi
