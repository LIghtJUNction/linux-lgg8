# C224 observation experiment

This directory preserves the source of the C224 read-only observation
experiment and its offline tests. It is a device-specific research artifact,
not a general-purpose charging driver or a validated device test procedure.
The source was initially moved from the ignored `out/` experiment directory
with only the paths to local artifacts changed; see `lgg8/docs/STATUS.md` for
the historical hashes, results, and limitations. Later C225 observations
exposed host transport defects: the current source clears partial terminal
input, waits for a fresh prompt, answers cursor-position queries, and parses
receipt metadata only inside its complete result frame. The historical C224
output files and their recorded hashes have not been replaced. Transient
device-node permission or disappearance errors are retried within the original
observation deadline, with identity checked again after opening the tty.

The scripts look for locally retained files under:

* `out/lgg8-c224-fg-presence-observe-20261031/`: the pinned C224 boot image,
  manifest, and build provenance.
* `out/lgg8-c223-smb5-icl-observe-20261031/`: the C223 baseline manifest.
* `out/lgg8-c210-sw42000-touch-20261031/`: the pinned legacy helper.

These experiment outputs are not included in a fresh clone. The offline test
suite runs its simulated tests without them and explicitly skips the two
artifact-dependent tests. If any of the expected artifacts exist, both checks
run and missing or mismatched files fail rather than being silently skipped.
Temporary test files are created within the workspace and cleaned afterward.
The suite does not run device commands:

```sh
python3 -B lgg8/experiments/c224-observer/test_c224_offline.py
```

Integration tests run the generated shell script with the pinned ARM64
BusyBox under `qemu-aarch64`, including an injected SHA-256 applet failure
and an interactive PTY session with partial input and command echo. A PTY
protocol test also splits a cursor-position query across two reads. These
tests skip explicitly when QEMU or the local BusyBox is absent;
an available BusyBox with the wrong hash fails. The tests redirect their
temporary paths to the workspace and do not run on the phone.

Running `run-c224-observe.py` without arguments performs only an offline review
and also requires the pinned files. Its explicit device execution path is
retained for audit, but **C224 has not been booted or validated**. A connected
USB cable can supply power and inherited charging may continue. Temperature
freshness, actual charging stop, and fault protection remain unverified; do not
use this experiment to enable or evaluate charging until those gaps have been
resolved. Neither its offline tests nor recovery checks establish charging
safety.
