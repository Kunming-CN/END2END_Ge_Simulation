# Recover an interrupted parent update

```powershell
.\Run.cmd recover -Name MY_RUN -DryRun -Json
.\Run.cmd recover -Name MY_RUN -Json
```

This explicit action reconciles a **completed guarded native child** with its
interrupted campaign parent. The menu's **R** option opens the same action.
Only `-Name`, `-DryRun` and `-Json` are accepted; even explicitly supplied default
run/settings options are rejected. Recovery performs no runtime readiness check,
Julia/WSL lookup, simulation, calibration, per-group resume or electronics replay.

New campaigns durably save `MODEL/native-launch-intent.json` and its hash in
`run.json` before launching the native child. The versioned intent binds the exact
executable/arguments, output location, detector/census, stream/prepared/transport
receipts, profile and independently resolved configuration, model and consumer
sources, guard requirement and immutable campaign context. It cannot authorize an
already existing output. Normal resume refuses pending intents, including an
intent whose output has disappeared.

Recovery opens the **existing** `run.lock` exclusively without creating it. It
uses the shared validators for saved inputs, artifacts, sources, settings, guard,
counts and existing parent bindings. A missing intent, legacy orphan, missing or
partial pending child, pre-guard receipt, changed dependency, incompatible resealed
configuration or held/missing lock blocks recovery. Historical source receipts
are never rebased. Current-source incompatibility does not imply corrupt science.

After validation, `recovery-v1/BEFORE_SHA256/` holds an additive transaction:

1. Exact original `parent-before.json` and durably staged `parent-after.json`.
2. Immutable `PREPARED.json`, binding both parent hashes and verified child hashes.
3. Atomic parent replacement, retaining `parent-replaced-before.json` as well.
4. Additive `COMMITTED.json`, binding the prepared receipt and resulting parent.

PREPARED is never a claim that replacement succeeded. Reentry with the before
parent revalidates and finishes; reentry with the after parent finalizes the
marker only. Neither parent hash blocks recovery. Interrupted staging is retained;
exact intact staging can be continued, while truncated/different evidence blocks
without overwrite or deletion. Dry-run reports the boundary without repairing it.
Any failure after staging may leave evidence; preserve it for inspection.

A valid complete parent is a read-only no-op. When another selected detector has
not produced a pending native child, recovery leaves `nonterminal_recovered` and
launches nothing. A missing/corrupt **parent-bound** child always blocks reuse.
Repeated recovery never duplicates stages or updates events. Existing stage
history, errors, timestamps and measured timings remain original; transaction
receipts explain the later metadata change. Native-failed status/counts, zeros,
null responses and all scientific files are unchanged. Processing completion is
not complete-waveform coverage, calibrated detector accuracy or experimental fit.

`tools/test_native_recovery.py` exercises the public CLI and driver using the
explicitly mocked `electronics_execution_fixture.py`. Process-death hooks exist
only in fixture copies, installed before their source hashes are recorded. These
tests verify orchestration and metadata integrity, not physics. Existing immutable
science is not a test output or a migration target.
