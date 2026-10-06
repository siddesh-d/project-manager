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

## Download PM2 Logs

Open a service's More Actions menu and select DOWNLOAD LOGS. Select an output,
error, or configured combined log, then select DOWNLOAD. The file list includes
each PM2 instance's ID, filename, and size, including stopped instances still
registered in PM2. REFRESH reloads the available files.

Downloads use PM2's stored log files, not the live console stream. Platform
admins can download logs for any PM2 service; tenant users can download logs
only for projects they can access. Missing files are omitted. Removed PM2
processes and archived or rotated files are not included in this picker.
