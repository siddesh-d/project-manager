# project-manager

## PM2 Cluster Instances

Select RUN in Projects or RESTORE SERVICE in the service dashboard to open the
start dialog. Enable Cluster Mode and enter a positive instance count. Leaving
Cluster Mode off keeps the existing PM2 start behavior.

The command console also accepts `start <project-name> --instances 4`.
PM2's `--instances` option starts Node.js runtime entries in cluster mode,
including an explicit count of 1. Custom start commands and non-Node projects
do not support this option. The count applies to this start request; restarting
the resulting PM2 service keeps its PM2 configuration. Tenant project access
restrictions continue to apply.
