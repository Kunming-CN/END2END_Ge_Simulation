# Native batch: progress-display permission recovery

The September 27 native worker stopped after 1,870 committed pulse groups because
replacing `progress.html` raised Windows `EACCES`. The stack points to the display
update AFTER `commit`, not carrier drift or result serialization. The failed state
was subsequently written successfully, and the inspected file was not read-only.
Transient file access contention is plausible; the specific competing process was
not identified. Do not blame the browser, synchronization or antivirus as proven.

All 1,870 result binaries and DONE hashes were checked: 1,843 native completions,
27 separately recorded numerical failures, and 1,621 accepted ADCs. There were no
orphan binaries. The 27 numerical failures are not this display error. The original
configuration, numerical source hashes, event inputs and both field caches match.
The pre-resume inventory records hashes, sizes and modification times for 3,747 files.

`native_progress_resilience.jl` is an additive, source-pinned display adapter.
It replaces only `progress()` JSON/HTML publishing in the current process. Permission
or sharing errors receive three bounded attempts, then an explicit warning. An
unavailable display can be stale; DONE/result files remain authoritative. Other
errors, including disk-full and programming errors, still propagate. Scientific
`atomic_write`, commit, recovery, numerical validation and physics are unchanged.

`resume_native_progress.py` binds this extension separately to the existing config;
no old hashes are rebased. It retains child-process ownership through display errors,
records numeric exit codes in unique logs, and keeps the existing exclusive locks.
Use it rather than the original launcher for this interrupted campaign.

Validation: 17 Julia display-only fault-injection assertions and 5 Python launcher
checks passed. Two existing reviewers inspected the limited change; their child
ownership finding was corrected and rechecked. No new physics tests were needed.
A real resume validated every original checkpoint and processed exactly ONE new
group, reaching 1,871, then paused with process exit 0. Rechecking all 3,747 snapshot
files found identical hashes, sizes and modification times. No completed group
was recomputed, and no original configuration or numerical source was changed.

The campaign's `Resume.cmd` now selects this recovery entry. `Monitor.cmd`,
`progress.html` and `Pause-After-Group.cmd` remain the user controls. A visible
recovery console observes the worker; closing the progress browser is harmless.
Terminal process receipts and COMPLETE take precedence over a stale display.
Evidence remains in `.local/native-progress-recovery/` and unique campaign logs.

Windows sharing semantics: a handle without FILE_SHARE_DELETE can prevent rename;
see Microsoft CreateFileW documentation. This explains a possible mechanism,
not proof of which program held the file during this particular incident.
