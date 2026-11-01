# In-app scheduled daily sweep

The system had no clock: every fan-out was human- or agent-poked, and missed days meant blind mornings. We decided the scheduler lives inside the boldtrader server as a daemon thread — no cron, no systemd units, no side processes — because the deployment is a single process and the operator wants it to stay that way. The timer fires daily at 06:00, and at boot whenever the last recorded sweep is older than ~20 hours, so crashes and reboots self-heal into a catch-up sweep instead of a silent skip.

Consequences: the sweep's own state (last-run timestamp) must persist in the DB, not memory; the scheduler thread must survive a bad sweep night without taking the server down; and "stop the schedule" means stopping the server until a pause API exists (deliberately deferred).
