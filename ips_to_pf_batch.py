"""
IPS to PowerFactory mastering pipeline - scheduled entry point.

This module is the top of a three-repository pipeline that transfers
protection relay settings from IPS into the PowerFactory master models
and runs a protection assessment over the result:

    ProtectionBatchRunner (this repo)
        ips_to_pf_batch.py           <- entry point (this module)
          derive_latest_versions()       derive the latest version of each
                                         master project into a fresh
                                         "Ready to Master" folder
          batch_relay_update.main()      per-project loop:
            |
            |-- IPStoPF\\main.py          IPS -> PF settings transfer for
            |   (ips_to_pf.main)         the active project
            |
            |-- create_version()         version the project as the audit
            |                            record of the import
            |
            '-- SystemProtectionAssessment\\start.py
                (start.begin)            fault level study + conductor
                                         damage assessment
          change_permissions()           share derived projects (stubbed)

Designed to run unattended (weekly Windows Task Scheduler) over the full
master-projects fleet, or a single project in pilot mode. Configuration,
scheduling, exit codes and failure handling are documented in README.md.
"""

import sys
import os
import logging
from pathlib import Path
from contextlib import contextmanager
import yaml
# Dummy place holders for global imports
pf = None 
pftextoutputs = None
bru = None
# PowerFactory runtime + helper module locations (single source of truth)
PF_PYTHON_DIR = r"C:\Program Files\DIgSILENT\PowerFactory 2025 SP3\Python\3.12"
PF_INSTALL_DIR = str(Path(PF_PYTHON_DIR).parents[1])  # ...\PowerFactory 2025 SP3
PF_TEXT_OUTPUTS_DIR = r"\\Ecasd01\WksMgmt\PowerFactory\Scripts\pfTextOutputs"

YAML_DIR = r"C:\LocalData\ProtectionBatchRunner"

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# TODO remove std out logging once email logging is working
std_out_handler = logging.StreamHandler(sys.stdout)
std_out_handler.setLevel(logging.DEBUG)
std_out_handler.setFormatter(
    logging.Formatter(
        "%(asctime)s: %(filename)s: %(lineno)d:\t%(message)s",
        datefmt="%Y-%m-%d %H:%M:%S%z",
    )
)
root_logger = logging.getLogger()
root_logger.setLevel(logging.DEBUG)
root_logger.addHandler(std_out_handler)

# Ensure app loggers stay at INFO so their records reach the stdout handler on root
for name in (
    "ips_data", "update_powerfactory", "config", "core", "utils",
    "logging_config",
    # SystemProtectionAssessment namespaces
    "start", "fault_study", "cond_damage", "save_results", "relays",
    "assets", "fdr_open_points",
):
    logging.getLogger(name).setLevel(logging.INFO)


# Exit codes consumed by Windows Task Scheduler ("Last Run Result")
EXIT_SUCCESS = 0          # all projects processed successfully
EXIT_PARTIAL_FAILURE = 1  # run completed but one or more projects failed
EXIT_FATAL = 2            # run aborted (no app, no projects, or unhandled error)


def run_main():
    """Entry point for scheduled execution.

    Returns:
        Process exit code: EXIT_SUCCESS, EXIT_PARTIAL_FAILURE or EXIT_FATAL.
    """

    yaml_ini_file = os.path.join(YAML_DIR, "pf_login.yaml")

    try:
        d = get_yaml_d(yaml_ini_file)
        import_required_pf_modules()

        with produce_secured_app_instance(d, yaml_ini_file, logger=logger) as app:
            if app is None:
                logger.error("PowerFactory application instance is None")
                return EXIT_FATAL
            print("Secure connection created")  # noqa
            with pftextoutputs.PowerFactoryLogging(
                pf_app=app,
                add_handler=True,
                handler_level=logging.DEBUG,
                logger_to_use=logger,
                formatter=pftextoutputs.PFFormatter(
                    "%(module)s: Line: %(lineno)d: %(message)s"
                ),
            ) as pflogger:
                total, failed = main(app)
    except Exception:
        logger.exception("Mastering run aborted by unhandled exception")
        return EXIT_FATAL

    # Run summary
    if total == 0:
        logger.error("RUN SUMMARY: no projects processed")
        return EXIT_FATAL
    if failed:
        logger.error(
            f"RUN SUMMARY: {len(failed)} of {total} projects failed: "
            f"{', '.join(failed)}"
        )
        return EXIT_PARTIAL_FAILURE
    logger.info(f"RUN SUMMARY: all {total} projects completed successfully")
    return EXIT_SUCCESS


def main(app):
    """Run the full mastering pipeline and return a run summary.

    Pipeline: derive latest project versions -> batch relay update
    (IPS settings transfer + version + protection assessment per project)
    -> share permissions.

    Returns:
        Tuple of (total_projects, failed_project_names). A total of 0
        indicates derivation produced nothing to process, which the
        caller should treat as a failed run.
    """

    app.ClearOutputWindow()
    # Pilot mode: only the named project is derived and processed. For the
    # full fleet run, pass pilot=None. Pilot projects:
    # Atherton (ATHE, project: Tablelands), Mossman (MOOF/MOSS, project: Tablelands),
    # Postmans Ridge (PRG, project: Gatton-Postmans Ridge), Clayfield (CFD, project: Stafford).
    all_projects = derive_latest_versions(app, pilot="Tablelands")
    app.ReloadProfile()

    if not all_projects:
        logger.error("No projects were derived; nothing to process")
        return 0, []

    failed_projects = bru.main(app, all_projects)
    change_permissions(app, all_projects)
    return len(all_projects), failed_projects


def change_permissions(app, all_projects):
    """Share the project to the Ergon Publisher

    STATUS: deliberately disabled, not abandoned. The implementation below
    is drafted but commented out pending confirmation that automated
    sharing to ErgonPublisher is approved for the weekly run. To enable:
    uncomment the body and verify share_g/share_a behaviour on a single
    pilot project before a fleet run.
    """
    pass
    # cur_user = app.GetCurrentUser()
    # user_group = cur_user.GetAttribute("fold_id").SearchObject(
    #     "Cnf\Groups\ErgonPublisher.IntGroup"
    # )
    # app.SetWriteCacheEnabled(1)
    # for project in all_projects:
    #     logger.info(project)
    #     project.SetAttributeLength("share_g", 1)
    #     len_share = project.GetAttributeLength("share_g")
    #     logger.info(f"Length = {len_share}")
    #     project.share_g = [user_group]
    #     logger.info(project.share_g)
    #     project.SetAttributeLength("share_a", 1)
    #     project.share_a = [3]
    # app.SetWriteCacheEnabled(0)


def derive_latest_versions(app, pilot=None):
    """Derive the latest version of every in-scope master project.

    The master folders are located under the Publisher user. Only projects
    whose parent folder is one of the following are updated:
        - Regional Models\\Northern
        - Regional Models\\Southern
        - SEQ Models

    Derived projects are created in a fresh "Ready to Master" folder under
    the current user (the previous run's folder is deleted first).

    Args:
        app: PowerFactory application instance.
        pilot: Optional project name (str). If given, only the matching
            project is derived. Raises ValueError if no project matches,
            so a typo cannot silently produce an empty run.

    Returns:
        List of derived IntPrj objects. Master projects with no version,
        and versions whose derivation fails, are logged and skipped.
    """
    cur_user = app.GetCurrentUser()
    northern_fold = cur_user.GetAttribute("fold_id").SearchObject(
        "Publisher\\MasterProjects\\Regional Models\\Northern.IntFolder"
    )
    southern_fold = cur_user.GetAttribute("fold_id").SearchObject(
        "Publisher\\MasterProjects\\Regional Models\\Southern.IntFolder"
    )
    seq_fold = cur_user.GetAttribute("fold_id").SearchObject(
        "Publisher\\MasterProjects\\SEQ Models"
    )
    for folder in cur_user.GetContents("*.IntFolder"):
        if folder.loc_name == "Ready to Master":
            folder.Delete()
            break
    derive_location = cur_user.CreateObject("IntFolder", "Ready to Master")
    master_projects = []
    for folder in [northern_fold, southern_fold, seq_fold]:
        master_projects += folder.GetContents("*.IntPrj")
    if pilot:
        master_projects = [
            project for project in master_projects if project.loc_name == pilot
        ]
        if not master_projects:
            raise ValueError(
                f"Pilot project '{pilot}' not found in the master folders"
            )

    # Test code for running SystemProtectionAssessment only. Delete prior to production
    # projects = []
    # cur_user = app.GetCurrentUser()
    # fold = cur_user.GetContents("Ready to Master.IntFolder")[0]
    # projects += fold.GetContents("*.IntPrj")

    projects = []
    app.SetWriteCacheEnabled(1)
    app.EchoOff()
    try:
        for i, project in enumerate(master_projects):
            if i % 10 == 0:
                print(f"{i} projects have been derived")
            prjt_ver = project.GetLatestVersion(0)
            if not prjt_ver:
                logger.warning(f"{project.loc_name} has no version; skipping")
                continue
            derived = prjt_ver.CreateDerivedProject(
                f"{project.loc_name}", derive_location
            )
            if not derived:
                logger.warning(
                    f"CreateDerivedProject failed for {project.loc_name}; skipping"
                )
                continue
            projects.append(derived)
    finally:
        app.EchoOn()
        app.WriteChangesToDb()
        app.SetWriteCacheEnabled(0)

    return projects


def get_yaml_d(yaml_ini_file):
    """Get the Yaml Dictionary"""
    with open(yaml_ini_file) as yaml_f:
        d = yaml.safe_load(yaml_f)
    return d


def get_key_from_yaml(d, key, yaml_ini_file):
    """Get a key from a loaded yaml file"""
    try:
        value = d[key]
    except KeyError:
        logging.error(f"No {key} attribute in {yaml_ini_file}")
        raise
    return value


@contextmanager
def produce_secured_app_instance(d, yaml_ini_file, logger=logger):
    user = get_key_from_yaml(d, "user", yaml_ini_file)
    password = get_key_from_yaml(d, "password", yaml_ini_file)
    file_dir = get_key_from_yaml(d, "file_dir", yaml_ini_file)
    ini_file = get_key_from_yaml(d, "ini_file", yaml_ini_file)

    call_function = f'/ini "{file_dir}\\{ini_file}"'
 
    logger.info(f"Call function is {call_function}")
    logger.info(f"user is {user}")
 
    try:
        app = pf.GetApplicationExt(user, password, call_function)
    except pf.ExitError:
        logger.exception("Unable to get application")
        raise
 
    logger.info(f"Opened {app}")

    try:
        yield app
    finally:
        active_project = app.GetActiveProject()
        if active_project:
            active_project.Deactivate()


def import_required_pf_modules():
    """Configure sys.path and import the PowerFactory runtime + helper modules.

    Deferred (not imported at module top) so this module stays importable on
    machines without PowerFactory. Must run once before any code touches `pf`.
    """
    global pf, pftextoutputs, bru

    # powerfactory.pyd depends on the PF engine DLLs in PF_INSTALL_DIR. On
    # Python 3.8+ these are NOT resolved via PATH, so register the directory
    # explicitly before importing — otherwise the import fails with
    # "DLL load failed ... The specified module could not be found".
    os.add_dll_directory(PF_INSTALL_DIR)

    if PF_PYTHON_DIR not in sys.path:
        sys.path.append(PF_PYTHON_DIR)
    import powerfactory as pf

    if PF_TEXT_OUTPUTS_DIR not in sys.path:
        sys.path.append(PF_TEXT_OUTPUTS_DIR)
    import pftextoutputs

    import batch_relay_update as bru


if __name__ == "__main__":
    sys.exit(run_main())
