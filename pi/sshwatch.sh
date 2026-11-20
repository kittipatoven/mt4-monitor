#!/bin/bash
# MT4 Trading Monitor - SSH watchdog (run every 5 minutes by mt4-sshwatch.timer).
# On this Pi the SSH server has twice stopped answering while everything else kept
# running (cause not yet known). If sshd does not send its greeting, restart it so
# remote access comes back without unplugging the Pi. Logs to the journal.
banner="$(timeout 8 bash -c 'exec 3<>/dev/tcp/127.0.0.1/22 && head -c 7 <&3' 2>/dev/null)"
case "$banner" in
  SSH-*) exit 0 ;;
esac
logger -t mt4-sshwatch "sshd did not answer on port 22 (got: '${banner}') - restarting ssh"
systemctl restart ssh
