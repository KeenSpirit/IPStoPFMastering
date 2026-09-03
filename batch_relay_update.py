"""
Batch relay update - per-project loop of the mastering pipeline.

For each derived project supplied by ips_to_pf_mastering, this module:
    1. Activates the project (with activation verified by polling)
    2. Runs the IPStoPF settings transfer (ips_to_pf.main)
    3. Creates a dated version as the audit record of the import
    4. Runs the SystemProtectionAssessment (start.begin) inside
       helper.app_manager so calculation/echo/GUI state is initialised

Per-project failures are caught, logged and skipped; main() returns the
list of failed project names for the mastering layer's run summary.

IMPORT-ORDER DEPENDENCY: this module imports `powerfactory` at the top
level, which only resolves after the host process has registered the PF
install directory and appended PF_PYTHON_DIR to sys.path (see
ips_to_pf_mastering.import_required_pf_modules). It is not importable
standalone outside that context or a PowerFactory-embedded interpreter.
The sys.path.append calls below likewise hardwire the locations of the
IPStoPF and SystemProtectionAssessment repositories.
"""

import logging
import powerfactory as pf
import time
import sys
from pathlib import Path
from typing import Optional

# sys.path.append(r"\\Ecasd01\WksMgmt\PowerFactory\ScriptsDEV\IPStoPF")
sys.path.append(r"\\ntgcca1\ntdpe\PROTECTION\STAFF\Dan Park\PowerFactory\Dan script development\IPStoPF")
import main as ips_to_pf
# sys.path.append(r"\\Ecasd01\WksMgmt\PowerFactory\ScriptsDEV\SystemProtectionAssessment")
sys.path.append(r"\\ntgcca1\ntdpe\PROTECTION\STAFF\Dan Park\PowerFactory\Dan script development\SystemProtectionAssessment")
import start
import pf_protection_helper as helper

logger = logging.getLogger(__name__)

# Directory for assessment result workbooks in batch runs. None
# preserves the legacy per-user Citrix/LocalData behaviour. For
# unattended runs this should point at the results share so weekly
# outputs land beside the mastering run logs, rather than in the
# task account's LocalData on the VM.
# TODO: set to the production results directory, e.g.
# ASSESSMENT_OUTPUT_DIR = Path(r"\\ecasd01\WksMgmt\...\AssessmentResults")
ASSESSMENT_OUTPUT_DIR: Optional[Path] = None

# Root of the Power BI dashboard data store, in this repository's
# directory. Fact CSVs land in runs/<run_id>/ (accumulating history)
# and latest_lines/ (current state); run_manifest.csv records every
# project attempted, so the dashboard can tell "no exceptions" from
# "did not run". None disables all dashboard output.
DASHBOARD_DATA_DIR: Optional[Path] = (
    Path(__file__).resolve().parent / "dashboard_data"
)

MANIFEST_COLUMNS = [
    "run_id", "project", "status", "error",
    "started", "finished", "duration_s",
    "dashboard_device_rows", "dashboard_lines_csv",
]


def _local_timestamp() -> str:
    """Local time with UTC offset, matching the run log convention."""
    from datetime import datetime
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S%z")


def _append_manifest_row(run_dir: Path, row: dict) -> None:
    """
    Append one project outcome to the run manifest.

    Plain append with the header written on first use - each project's
    outcome is on disk the moment it is known, so a crash mid-fleet
    leaves a manifest that is accurate up to the crash. Deliberately
    implemented here rather than imported from the assessment repo:
    both repo roots share sys.path in this process, and the manifest
    describes the run, which only this layer can see.
    """
    import csv
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "run_manifest.csv"
    new_file = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=MANIFEST_COLUMNS,
            restval="", extrasaction="ignore",
        )
        if new_file:
            writer.writeheader()
        writer.writerow(row)

def main(app=None, all_projects=None):
    """Update all relays in a project"""
    if not app:
        app = pf.GetApplication()
    # All the folders under this folder needs the relays updated
    if not all_projects:
        current_script = app.GetCurrentScript()
        projects_folder = current_script.object_to_update
        all_projects = all_relevant_objects([projects_folder], "*.IntPrj")

    # Broken projects are handled per-iteration below: a failed Activate()
    # (exception or error return) is caught, logged and skipped.
    failed_projects = []

    # Cleared when PowerFactory itself dies. Every subsequent call
    # through `app` raises once that happens, so the teardown after the
    # loop must be skipped rather than allowed to crash out of main()
    app_alive = True

    # One run id for the whole fleet pass; every project's facts and
    # manifest row carry it, which is what lets the dashboard compare
    # run against run.
    run_id = time.strftime("%Y%m%d_%H%M%S")
    run_dir = None
    if DASHBOARD_DATA_DIR is not None:
        run_dir = DASHBOARD_DATA_DIR / "runs" / run_id
        logger.info(f"Dashboard run {run_id}; facts and manifest -> {run_dir}")

    for i, project in enumerate(all_projects):
        # app.SetGuiUpdateEnabled(1)
        app.ClearOutputWindow()
        app.PrintInfo(
            "Project {} is {} of {} is being worked on".format(
                project, i + 1, len(all_projects)
            )
        )
        logger.info(
            "Project {} is {} of {} is being worked on".format(
                project.loc_name, i + 1, len(all_projects)
            )
        )
        started = _local_timestamp()
        clock = time.perf_counter()
        summary = None
        try:
            # app.SetGuiUpdateEnabled(0)
            if project.Activate():
                raise RuntimeError(
                    f"Activate() returned an error code for {project.loc_name}"
                )
            wait_for_active_project(app, project)
            app.ClearOutputWindow()
            ips_to_pf.main(app, True)
            with helper.app_manager(app, gui=False, cache=True) as app:
                summary = start.begin(
                    app,
                    output_dir=ASSESSMENT_OUTPUT_DIR,
                    dashboard_dir=DASHBOARD_DATA_DIR,
                    dashboard_run_id=run_id,
                )
            logger.info(f"Assessment summary: {summary}")
            new_version = create_version(
                project, f'{time.strftime("%Y%m%d")} IPS Import'
            )
        except start.AssessmentError as err:
            # Typed per-project skip raised by start.begin (e.g. missing
            # study case). The settings transfer and version for this
            # project completed before the assessment bailed.
            logger.error(
                f"Assessment skipped for {project.loc_name}: {err}"
            )
            print(f"*** {project.loc_name} assessment SKIPPED: {err} ***")
            failed_projects.append(f"{project.loc_name} (assessment: {err})")
            if run_dir is not None:
                _append_manifest_row(run_dir, {
                    "run_id": run_id,
                    "project": project.loc_name,
                    "status": "ASSESSMENT_SKIPPED",
                    "error": str(err),
                    "started": started,
                    "finished": _local_timestamp(),
                    "duration_s": round(time.perf_counter() - clock, 1),
                })
            continue
        except pf.ExitError as err:
            # The PowerFactory session itself has died. Every remaining
            # project would fail on the dead handle, and any further
            # call through `app` raises again - including the ones in
            # this module's own cleanup. Record the outcome and stop
            # the fleet pass deliberately, rather than crashing out
            # through code that assumes a live application.
            logger.exception(
                f"PowerFactory session lost during {project.loc_name}; "
                f"aborting the remainder of this run"
            )
            print(
                f"*** PowerFactory session LOST during {project.loc_name} - "
                f"run aborted, {len(all_projects) - i - 1} project(s) not "
                f"attempted ***"
            )
            failed_projects.append(f"{project.loc_name} (PF session lost)")
            if run_dir is not None:
                _append_manifest_row(run_dir, {
                    "run_id": run_id,
                    "project": project.loc_name,
                    "status": "PF_SESSION_LOST",
                    "error": repr(err),
                    "started": started,
                    "finished": _local_timestamp(),
                    "duration_s": round(time.perf_counter() - clock, 1),
                })
                for remaining in all_projects[i + 1:]:
                    _append_manifest_row(run_dir, {
                        "run_id": run_id,
                        "project": remaining.loc_name,
                        "status": "NOT_ATTEMPTED",
                        "error": "PowerFactory session lost earlier in run",
                        "started": "",
                        "finished": _local_timestamp(),
                    })
            app_alive = False
            break
        except Exception as err:
            logger.exception(
                f"Project {project.loc_name} failed; continuing with next project"
            )
            print(f"*** Project {project.loc_name} FAILED - see traceback above ***")
            failed_projects.append(project.loc_name)
            if run_dir is not None:
                _append_manifest_row(run_dir, {
                    "run_id": run_id,
                    "project": project.loc_name,
                    "status": "FAILED",
                    "error": repr(err),
                    "started": started,
                    "finished": _local_timestamp(),
                })
            continue

        if run_dir is not None:
            dashboard = (
                summary.get("dashboard") if isinstance(summary, dict) else None
            )
            _append_manifest_row(run_dir, {
                "run_id": run_id,
                "project": project.loc_name,
                "status": "SUCCESS" if dashboard else "SUCCESS_NO_DASHBOARD",
                "error": "",
                "started": started,
                "finished": _local_timestamp(),
                "duration_s": round(time.perf_counter() - clock, 1),
                "dashboard_device_rows": (dashboard or {}).get(
                    "device_rows", ""
                ),
                "dashboard_lines_csv": (dashboard or {}).get(
                    "lines_csv", ""
                ),
            })

    if app_alive:
        try:
            active_project = app.GetActiveProject()
            if active_project:
                active_project.Deactivate()
        except Exception:
            logger.warning(
                "Could not deactivate the active project during teardown; "
                "the run summary below is still valid",
                exc_info=True,
            )
    else:
        logger.error(
            "PowerFactory session was lost during this run; skipping "
            "project deactivation"
        )

    if failed_projects:
        print(f"{len(failed_projects)} of {len(all_projects)} projects failed:")
        for name in failed_projects:
            print(f"\t{name}")
    else:
        print(f"All {len(all_projects)} projects completed successfully")

    return failed_projects


def wait_for_active_project(app, project, timeout_s=20.0, poll_s=0.5):
    """Block until `project` is the active project, or raise on timeout.

    In the normal case the project is already active on the first poll.
    The timeout raise is caught by the per-project handler in main(), so a
    project that never becomes active is logged and skipped, not fatal.
    """
    deadline = time.monotonic() + timeout_s
    while True:
        active = app.GetActiveProject()
        if active and active.loc_name == project.loc_name:
            return
        if time.monotonic() >= deadline:
            raise RuntimeError(
                f"{project.loc_name} did not become the active project "
                f"within {timeout_s}s"
            )
        time.sleep(poll_s)


def create_version(project, name):
    """Create a new version in the given project with the name supplied.

    The version is the audit record of the weekly IPS import, so failure
    to create one is logged rather than silently ignored. loc_name is
    truncated to PowerFactory's 40-character limit; notify=1 flags the
    version for user notification.

    Returns:
        The new IntVersion, or None if the input was not an IntPrj or
        CreateVersion() failed.
    """
    if not (
        project
        and isinstance(project, pf.DataObject)
        and project.GetClassName() == "IntPrj"
    ):
        logger.warning(f"create_version called with a non-project object: {project}")
        return None
    new_version = project.CreateVersion()
    if not new_version:
        logger.warning(f"CreateVersion() failed for {project.loc_name}")
        return None
    new_version.SetAttribute("loc_name", name[:40])
    new_version.SetAttribute("notify", 1)
    return new_version


def all_relevant_objects(folders, type_of_obj, objects=None):
    """The protection user has multiple stages for projects. Only a single
    project for each substation is to be used if it has been reviewed"""
    for folder in folders:
        if not objects:
            objects = folder.GetContents(type_of_obj)
        else:
            objects += folder.GetContents(type_of_obj)
        sub_folders = folder.GetContents("*.IntFolder")
        if sub_folders:
            objects = all_relevant_objects(sub_folders, type_of_obj, objects)
    return objects


if __name__ == "__main__":
    main()