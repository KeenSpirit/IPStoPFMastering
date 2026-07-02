# IPStoPFMastering

Scheduled entry point for the IPS → PowerFactory protection settings pipeline.
This repository orchestrates two downstream repositories — **IPStoPF**
(settings transfer) and **SystemProtectionAssessment** (fault level study and
conductor damage assessment) — across the PowerFactory master-projects fleet
(~80 projects), on a weekly unattended cadence.

## Pipeline overview

```
ips_to_pf_mastering.py  (run by Windows Task Scheduler)
│
├── derive_latest_versions()
│       Derives the latest version of every master project under
│       Publisher\MasterProjects (Regional Models\Northern,
│       Regional Models\Southern, SEQ Models) into a fresh
│       "Ready to Master" folder. The previous run's folder is deleted.
│
├── batch_relay_update.main()          ── per derived project ──
│       ├── project.Activate()          (verified by polling, not sleep)
│       ├── IPStoPF\main.py             IPS → PF settings transfer
│       ├── create_version()            dated version = audit record
│       └── SystemProtectionAssessment\start.py (start.begin)
│               fault level study + conductor damage assessment,
│               run inside pf_protection_helper.app_manager
│
└── change_permissions()
        Share derived projects to ErgonPublisher — currently a stub,
        deliberately disabled (see docstring in ips_to_pf_mastering.py).
```

Per-project failures are caught, logged and skipped; the run continues and
the failed projects are reported in the run summary and exit code.

## Repository contents

| File | Purpose |
|---|---|
| `ips_to_pf_mastering.py` | Entry point. Logging setup, PF login, derivation, run summary, exit codes. |
| `batch_relay_update.py` | Per-project loop: activate → transfer → version → assess. |
| `pf_login.yaml` | PowerFactory credentials and ini file location (not in version control). |
| `README.md` | This file. Supersedes the old `NOTES.md`. |

## Prerequisites

1. **DIgSILENT PowerFactory 2025 SP3** installed on the execution machine
   (target: VM SOEV01948).
2. **Python interpreter matching a PF-supplied API version.** Check what you
   are launching with:

   ```
   python -c "import sys; print(sys.version); print(sys.maxsize > 2**32)"
   ```

   Then confirm `PF_PYTHON_DIR` in `ips_to_pf_mastering.py` points at the
   matching folder, e.g. for a 3.12 interpreter:

   ```python
   PF_PYTHON_DIR = r"C:\Program Files\DIgSILENT\PowerFactory 2025 SP3\Python\3.12"
   ```

   `PF_INSTALL_DIR` is derived from `PF_PYTHON_DIR` (single source of truth) and
   is registered via `os.add_dll_directory()` before importing `powerfactory` —
   on Python 3.8+ the PF engine DLLs are **not** resolved via `PATH`, and
   skipping this step fails with `DLL load failed`. A version mismatch between
   interpreter and `PF_PYTHON_DIR` produces the same error.
3. **Network access** to the IPStoPF and SystemProtectionAssessment
   repositories (paths are appended to `sys.path` at the top of
   `batch_relay_update.py`) and to `pftextoutputs`
   (`PF_TEXT_OUTPUTS_DIR` in `ips_to_pf_mastering.py`).
4. **IPS/ODS database access** as required by IPStoPF (see that repository's
   README for `cx_Oracle` configuration).

## Configuration

### Credentials file (`pf_login.yaml`)

Path is set by `yaml_ini_file` in `run_main()`. Required keys:

```yaml
user:      <PowerFactory username>
password:  <PowerFactory password>
file_dir:  <directory containing the ini file>
ini_file:  <PowerFactory ini file name>
```

The password is stored in plain text — keep the file on the execution VM
(convention: `C:\LocalData\BatchStudy\`) with restrictive ACLs, not on a
shared drive. Never log the loaded dictionary wholesale.

### Paths hardcoded in source (update on redeployment)

| Location | Constant / variable |
|---|---|
| `ips_to_pf_mastering.py` | `PF_PYTHON_DIR` (drives `PF_INSTALL_DIR`), `PF_TEXT_OUTPUTS_DIR`, `yaml_ini_file` |
| `batch_relay_update.py` | `sys.path.append(...)` for the IPStoPF and SystemProtectionAssessment repos |

### Pilot vs fleet mode

`main(app)` calls `derive_latest_versions(app, pilot="Algester")`.

- **Pilot mode** — `pilot="<project name>"`: only the named project is
  derived and processed. A name that matches nothing raises `ValueError`
  (exit code 2) rather than silently doing nothing.
- **Fleet mode** — `pilot=None`: every project under the three master
  folders is processed.

Previously used pilot projects: Algester, Atherton, Mossman, Postmans Ridge,
Clayfield.

## Running manually

```
cd /d Y:\PROTECTION\STAFF\Dan Park\PowerFactory\Dan script development\IPStoPFMastering
python ips_to_pf_mastering.py
echo %ERRORLEVEL%
```

(`/d` allows `cd` to switch drive letters.) Expect a `RUN SUMMARY:` line at
the end of the console output and `%ERRORLEVEL%` per the table below.

## Scheduled execution (Windows Task Scheduler)

Configure the task on the execution VM with:

- **Action**: `python <repo path>\ips_to_pf_mastering.py`
  Optionally redirect output as a belt-and-braces console capture:
  `cmd /c python ips_to_pf_mastering.py >> C:\LocalData\BatchStudy\mastering_console.log 2>&1`
- **Run whether user is logged on or not**, with an account that has PF
  licence access and network drive access (map or use UNC paths — mapped
  drive letters are not available to non-interactive tasks by default).
- **Schedule**: weekly. <!-- TODO: record the agreed day/time and task name here once created -->
- **Settings**: do not start a new instance if one is already running
  (a fleet run takes hours; overlapping PF sessions will fail on licence).

Task Scheduler records the exit code as "Last Run Result" but takes no
action on it by default — check it after each run, or add an alerting
wrapper (see roadmap).

## Exit codes

| Code | Meaning | Operator action |
|---|---|---|
| 0 | All projects completed successfully | None |
| 1 | Run completed; one or more projects failed | Check `RUN SUMMARY:` for the failed list, then per-project tracebacks in the log |
| 2 | Run aborted: no PF app, no projects derived, pilot name not found, or unhandled exception | Read the traceback; the run did not process the fleet |

## Logging

- **Console / stdout** — a single `StreamHandler` on the root logger
  (DEBUG). All module loggers propagate to it, including per-feeder
  assessment progress (`[i/N] feeder: stage`) from SystemProtectionAssessment.
  Under Task Scheduler there is no console — persist output via the
  redirect in the task action shown above.
- **PowerFactory output window** — bridged via `pftextoutputs
  .PowerFactoryLogging` while the app is open.
- **IPStoPF JSON log** — the settings-transfer layer writes JSON Lines to
  `<IPStoPF repo>/results_log/ips_to_pf.log` (rotating, 10 MB × 5). Note its
  `setup_logging()` sets the root logger to WARNING; the mastering module
  pins the app-logger namespaces (`ips_data`, `update_powerfactory`,
  `config`, `core`, `utils`, `logging_config`) back to INFO so their records
  still reach stdout.
- **Assessment results** — written by SystemProtectionAssessment's
  `save_results` layer (see that repository's documentation for the UNC
  results path).

## When a run fails

1. Check the exit code / "Last Run Result".
2. **Exit 1**: find the `RUN SUMMARY:` line, then search the log upward for
   each failed project's `Project <name> failed` traceback. Common causes:
   project fails to activate (verify it opens interactively), settings
   transfer errors (see IPStoPF log), assessment errors (see per-feeder
   progress lines to locate the stalling feeder).
3. **Exit 2**: the traceback at the end of the log identifies the abort
   point — credentials/licence (`Unable to get application`), pilot typo
   (`ValueError`), or empty derivation (`no projects processed`).
4. A failed project's derived copy remains in "Ready to Master"; it is
   replaced wholesale on the next run. To retry immediately, run in pilot
   mode with that project's name.

## Known limitations / roadmap

- **Email notification** of the run summary — outstanding TODO; the
  `RUN SUMMARY:` log line is the intended payload.
- **Module name collision risk**: both downstream repos sit on `sys.path`
  and contain generically named top-level modules (`main`, `start`, `utils`,
  `config`-like packages). Resolution order is append order. The planned
  installable-package refactor (`ips_pf_mapping` et al.) removes this class
  of problem.
- **Delta processing**: every project is processed every week regardless of
  whether its IPS settings changed. A pre-check on max `date_setting` per
  project against the last run date could skip untouched projects.
- **`change_permissions`** (ErgonPublisher sharing) is drafted but disabled
  pending approval.
- **EDW → Lakehouse migration** will require updates to the batch SQL in
  IPStoPF's `query_database.py` (`ENERGEX_BATCH_SQL` / `ERGON_BATCH_SQL`).