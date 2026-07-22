#!/bin/zsh
cd "$(dirname "$0")"
python3 server.py &
SERVER_PID=$!
sleep 1
open http://localhost:8000
wait $SERVER_PID
