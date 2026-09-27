# Independent, resumable Cs137 transport

This new route is **Geant4 only**. Each detector receives 1,000,000 initial Cs137 decays in the unchanged saved nominal assembly. The source remains uncollimated; no GPS/RDM cone settings, geometry, material, production-cut or native-SSD parameters are changed. Old runs remain frozen.

## Prepared input and launch

From the project root on the configured Windows computer, using the existing pinned WSL environment:

```powershell
.\transport\Run.cmd python -B ../tools/long_transport.py prepare --campaign .local/cs137-1m --events 1000000 --chunk-size 10000
.\tools\Start-Transport.ps1 -Campaign .local/cs137-1m
.\tools\Monitor-Transport.ps1 -Campaign .local/cs137-1m
```

`prepare` refuses an existing directory. `Start-Transport.ps1` starts an independent Windows worker and records its PID/start time. The calculation does not depend on the chat remaining open; no model, API or recurring ChatGPT task supervises it. Keep the computer powered and awake: the launcher does not alter the user's power plan. A reboot or power loss can interrupt the active chunk, but not erase completed checkpoints.

The default campaign has 100 chunks of 10,000 decays for AK02, then 100 for SAP22. Each has a recorded deterministic, distinct seed. `global_decay_id = chunk start + original event ID` within a detector; the campaign/configuration hash distinguishes runs. Chunking changes the random stream relative to the old 10k example, not the physical source. There is no cross-chunk absolute activity clock.

Open `.local/cs137-1m/progress.html` for a self-refreshing local status page. `progress.txt` and `progress.json` provide the same small records. Progress counts verified, committed decays, not a guessed number based on output size. The first-chunk ETA is absent until measured throughput exists; ETA is only an estimate. A stale heartbeat is explicitly warned, not interpreted as proof of a running task. Closing the monitor leaves the worker running.

## Pause and resume without starting over

To request a stop after the current chunk finishes, create the marker:

```powershell
New-Item .local/cs137-1m/STOP_AFTER_CHUNK -ItemType File
```

After the status says `paused`, remove only that control marker and resume:

```powershell
Remove-Item .local/cs137-1m/STOP_AFTER_CHUNK
.\tools\Start-Transport.ps1 -Campaign .local/cs137-1m
```

Completed chunks have a `DONE.json` whose configuration, original event ranges, file hashes and counts are checked before reuse. An OS-held advisory lock prevents simultaneous workers for the same campaign; its descriptor is inherited by transport while it runs. Stale lock-file contents are not an active lock. A raw file with a successful recorded process receipt is reduced/archived on resume, without rerunning remage. An incomplete transport attempt stays preserved; only that chunk may need a new attempt with the same seed. There are no unbounded automatic retries.

Sources, template files and runtime/data hashes are immutable for a prepared campaign. Stop and inspect mismatches; never edit/re-hash old receipts to force a restart. Every original scientific dependency remains checked. Finished transport writes `COMPLETE.json`, status `completed_transport`, and waits for later analysis. It never starts Julia, native charge transport or electronics.

## Stored records

Each successful chunk contains `compact.h5` and a lossless `truth.lh5.gz` archive. Compact records retain all primary scalar counts, zeros, emitted-line denominators and material energies; all Ge steps; all track histories for Ge-crossing primaries; and passive steps for Ge-positive primaries. Original column dtypes, units, selected float bits and raw row maps remain. Detailed records not duplicated in compact HDF5 remain recoverable from the original archive. Do not identify these saved particle steps with continuous unrecorded world-air trajectories.

New temporary raw LH5 is removed only after compact verification, decompressed archive SHA-256/size verification, and durable DONE publication. Old data and failed attempts are not deleted. HDF5 uses gzip, shuffle and Fletcher32, not lossy precision reduction. See [storage rationale and primary references](STORAGE_STRATEGY.md).

```powershell
.\transport\Run.cmd python -B ../tools/test_long_transport.py
.\transport\Run.cmd python -B ../tools/long_transport.py verify --campaign .local/cs137-1m
```

The tests use synthetic fixtures and recorded data, not a million-event run. A small real transport pilot separately exercises the detached launcher, pause/resume and unchanged completed-chunk receipt. Verification hashes original compressed artifacts; it does not generate new radiation events.
