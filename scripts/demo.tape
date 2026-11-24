# DQAgent terminal demo — records detect (L0/L1) then run (full agent patrol).
#
# Run on the server (needs the demo data already generated + DeepSeek key):
#   cd /data/home/hermes/dq-demo
#   set -a && . ./.env && set +a
#   export PATH="$PWD/.venv/bin:$PATH"
#   /data/home/hermes/bin/vhs scripts/demo.tape

Output demo.gif

Require dqagent

Set Shell "bash"
Set FontSize 16
Set Width 1000
Set Height 800
Set Padding 40
Set PlaybackSpeed 1.5

Type "dqagent detect --dir demo"
Enter
Sleep 4s

Type "dqagent run --dir demo"
Enter
Sleep 28s
Sleep 8s
