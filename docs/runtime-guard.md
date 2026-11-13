# Runtime guard on VK Cloud

The supervisor starts the existing Telegram/MAX worker as a child process.
It reads both worker and scheduler heartbeats every 30 seconds. Startup grace
is 240 seconds; a heartbeat older than 300 seconds triggers a bounded child
shutdown and relaunch. A database probe failure alone does not trigger a restart.
The named constants in runtime_guard.py control these limits.

After a child exits (and before every launch), in-flight publications are marked
ambiguous and in-flight dashboard actions failed. Completed deliveries are never
requeued. This intentionally prefers a visible manual reconciliation over a
possible duplicate. Interrupted posts can remain unpublished until reviewed.

Deployment uses an image layer on the actual cross:vpn-link-test image, preserving
its local SOCKS5 patch. Environment, user, host configuration, volume mounts and
network are cloned from the retained original container. No Telegram session is
opened by the supervisor itself. No settings or credentials are printed.

Runtime image: cross:runtime-guard-20261113.
Original container: cross-before-runtime-guard-20261113 (stopped).
Rollback: /home/ubuntu/cross/artifacts/runtime-guard-20261113/ROLLBACK.sh.
Rollback restores the original container, not delivered messages or queue history.
Never run the retained original container simultaneously with cross.

Tests include stale-scheduler detection while the worker heartbeat remains fresh,
startup grace, malformed timestamps, bounded forced shutdown, child relaunch,
and quarantine predicates. Production restart fault injection was not performed.
