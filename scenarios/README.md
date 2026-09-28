# Reviewed local scenarios

`Run.cmd` is the Windows entry point for users who want to run a reviewed
end-to-end example without writing simulation code. Scenario JSON files contain
scientific references and bounded presets only; they do not contain executable
commands or machine-specific dependency paths.

## LBNL Cs137 v1

`scenarios/lbnl-cs137.json` selects the nominal LBNL cryostat assembly,
uncollimated Cs137 source, the AK02/SAP22 detector choices, and the versioned
synthetic readout profile. The nominal source/cryostat geometry is not an
as-built survey or a calibrated experimental configuration.

From the repository root on Windows:

```console
Run.cmd check
Run.cmd setup
Run.cmd run -Preset demo -Detector both
Run.cmd status
Run.cmd resume -Name RUN_NAME
Run.cmd open -Name RUN_NAME
```

Presets are **smoke = 20**, **demo = 500**, and **larger = 10,000** initial
Cs137 decays per selected detector. Smoke is an installation check and may
produce no Ge pulse. Larger requires a verified clean 500-event pilot. Million
decay production is deliberately not exposed as a beginner preset.

The pinned upstream LBNL text-geometry files are not redistributed because no
explicit license was found in the pinned upstream tree. Setup checks the exact
inventory and SHA-256 hashes recorded in `transport/cryostat-source.json`
under `.local/transport/LBNL`. It does not silently substitute geometry.

Each new run is stored below `.local/runs/`. Completed stages have receipts
and hashes. Resume uses the saved run's event count, detector set and seed,
ignoring new command-line overrides. Hash-verified complete stages are reused;
incomplete stage directories are preserved and stop for inspection rather than
being deleted and rerun. Small-run v1 does not claim group-level resume inside
an interrupted native-response stage.

Future GeGI strip and larger-cryostat support should be added as separately
reviewed scenario adapters with explicit geometry, electrode/channel and
readout capabilities, not by loosening this scenario into arbitrary combinations.
