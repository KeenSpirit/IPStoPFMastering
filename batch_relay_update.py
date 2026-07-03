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

sys.path.append(r"\\ntgcca1\ntdpe\PROTECTION\STAFF\Dan Park\PowerFactory\Dan script development\IPStoPF")
import main as ips_to_pf
sys.path.append(r"\\ntgcca1\ntdpe\PROTECTION\STAFF\Dan Park\PowerFactory\Dan script development\SystemProtectionAssessment")
import start
import pf_protection_helper as helper

logger = logging.getLogger(__name__)

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
    for i, project in enumerate(all_projects):
        # app.SetGuiUpdateEnabled(1)
        app.ClearOutputWindow()
        app.PrintInfo(
            "Project {} is {} of {} is being worked on".format(
                project, i + 1, len(all_projects)
            )
        )
        print(
            "Project {} is {} of {} is being worked on".format(
                project.loc_name, i + 1, len(all_projects)
            )
        )
        try:
            # app.SetGuiUpdateEnabled(0)
            if project.Activate():
                raise RuntimeError(
                    f"Activate() returned an error code for {project.loc_name}"
                )
            wait_for_active_project(app, project)
            net_mod = app.GetProjectFolder("netmod")
            app.ClearOutputWindow()
            ips_to_pf.main(app, True)
            new_version = create_version(
                project, f'{time.strftime("%Y%m%d")} IPS Import'
            )
            with helper.app_manager(app, gui=False) as app:
                summary = start.begin(app)
            logger.info(f"Assessment summary: {summary}")
        except start.AssessmentError as err:
            # Typed per-project skip raised by start.begin (e.g. missing
            # study case). The settings transfer and version for this
            # project completed before the assessment bailed.
            logger.error(
                f"Assessment skipped for {project.loc_name}: {err}"
            )
            print(f"*** {project.loc_name} assessment SKIPPED: {err} ***")
            failed_projects.append(f"{project.loc_name} (assessment: {err})")
            continue
        except Exception:
            logger.exception(
                f"Project {project.loc_name} failed; continuing with next project"
            )
            print(f"*** Project {project.loc_name} FAILED - see traceback above ***")
            failed_projects.append(project.loc_name)
            continue

    active_project = app.GetActiveProject()
    if active_project:
        active_project.Deactivate()

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