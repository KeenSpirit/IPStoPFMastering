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
import re
import time
import keyring

# Dummy place holders for global imports
pf = None
pftextoutputs = None
bru = None
# PowerFactory runtime + helper module locations (single source of truth)
PF_PYTHON_DIR = r"C:\Program Files\DIgSILENT\PowerFactory 2025 SP3\Python\3.12"
PF_INSTALL_DIR = str(Path(PF_PYTHON_DIR).parents[1])  # ...\PowerFactory 2025 SP3
PF_TEXT_OUTPUTS_DIR = r"\\Ecasd01\WksMgmt\PowerFactory\Scripts\pfTextOutputs"

YAML_DIR = r"C:\LocalData\ProtectionBatchRunner"

## Global master projects variables
SEQ_MASTER_PROJECTS_FULL_NAME = r"\Publisher.IntUser\MasterProjects\SEQ Models"
EE_NORTHERN_MASTER_PROJECTS_FULL_NAME = (
    r"\Publisher.IntUser\MasterProjects\Regional Models\Northern"
)
EE_SOUTHERN_MASTER_PROJECTS_FULL_NAME = (
    r"\Publisher.IntUser\MasterProjects\Regional Models\Southern"
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

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
    "batch_relay_update", "main",
    "ips_data", "update_powerfactory", "config", "core", "utils",
    "logging_config",
    # SystemProtectionAssessment namespaces
    "start", "fault_study", "cond_damage", "save_results", "relays",
    "assets", "fdr_open_points",
    # Incremental-run fingerprints (IPStoPF incremental package)
    "incremental",
):
    logging.getLogger(name).setLevel(logging.INFO)


# Exit codes consumed by Windows Task Scheduler ("Last Run Result")
EXIT_SUCCESS = 0          # all projects processed successfully
EXIT_PARTIAL_FAILURE = 1  # run completed but one or more projects failed
EXIT_FATAL = 2            # run aborted (no app, no projects, or unhandled error)

def safe_load_pf_credentials():
    ## Get user credentials safely
    global USER
    global PASSWORD
    global PF_INSTALL_DIR
    global CALL_FUNCTION
    global PF_PYTHON_DIR

    ## Make sure credentials match user in yaml file
    cfg = yaml.safe_load(open("config.yaml"))
    USER = cfg["powerfactory"]["user"]
    ## This securely gets stored password from Microsoft Credential Manager
    PASSWORD = keyring.get_password(
        "PowerFactory",
        USER
    )
    ## Set up call function and python paths
    PF_INSTALL_DIR = cfg["powerfactory"]["file_dir"]
    ini_file = 'PowerFactory_PRD.ini'
    ## This version (3.12) can be unique to the computer
    PF_PYTHON_DIR = rf"{PF_INSTALL_DIR}\Python\3.12"
    CALL_FUNCTION = f'/ini "{PF_INSTALL_DIR}\\{ini_file}"'


def run_main():
    """Entry point for scheduled execution.

    Returns:
        Process exit code: EXIT_SUCCESS, EXIT_PARTIAL_FAILURE or EXIT_FATAL.
    """

    yaml_ini_file = os.path.join(YAML_DIR, "config.yaml")

    try:
        # d = get_yaml_d(yaml_ini_file)
        d = None
        import_required_pf_modules()

        with produce_secured_app_instance(d, yaml_ini_file, logger=logger) as app:
            if app is None:
                logger.error("PowerFactory application instance is None")
                return EXIT_FATAL
            logger.info("Secure connection created")  # noqa
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
    # all_projects = derive_latest_versions(app, pilot="Cleveland")
    app.ReloadProfile()

    ## Set this based on user
    cur_user = app.GetCurrentUser()
    global USER_DERIVED_MASTER_PROJECT
    USER_DERIVED_MASTER_PROJECT = rf"\{cur_user.loc_name}.IntUser\MasterProjects - Derived"

    if not USER_DERIVED_MASTER_PROJECT:
        logger.error("No projects were derived; nothing to process")
        return 0, []

    # workflow() derives all three regions, then runs the fleet once.
    return workflow(app)


def workflow(app):

    all_projects = []
    update_failed = []
    region_projects = [
        SEQ_MASTER_PROJECTS_FULL_NAME,
        EE_SOUTHERN_MASTER_PROJECTS_FULL_NAME,
        EE_NORTHERN_MASTER_PROJECTS_FULL_NAME
    ]
    for selected_folder in region_projects:
        logger.info(f"Start {selected_folder} projects")
        ## Use the selected_folder to determine suffix for folder structure
        user_suffix = get_region_suffix(selected_folder)
        current_user = app.GetCurrentUser()
        user_folder_path = current_user.GetContents(f'{USER_DERIVED_MASTER_PROJECT}\\{user_suffix}')[0]

        #PILOT = {"Richlands", "Runcorn"}
        #pilot_filter = lambda prjs: [p for p in prjs if p.loc_name in PILOT]

        ## 1) Check derived copies exist, if not then create
        create_region_copies(app, selected_folder, current_user)

        ## 2) Check if derived copies are latest version, if not then update to latest
        # Listed after step 1 so newly derived copies are included
        # update_derived_models(pilot_filter(user_folder_path.GetContents("*.IntPrj")), app)
        region_failures = update_derived_models(
            user_folder_path.GetContents("*.IntPrj"), app
        )

        ## TODO ask what this does, was in Dan's original workflow
        app.ReloadProfile()

        # Re-list AFTER step 2: UpdateToMostRecentBaseVersion replaces each
        # updated project (the old object is renamed and recycled), so any
        # handle taken before the update points at the recycle bin copy.
        # folder_contents = pilot_filter(user_folder_path.GetContents("*.IntPrj"))
        folder_contents = user_folder_path.GetContents("*.IntPrj")

        # A copy whose base version update failed is in an unknown state:
        # leave it out of the fleet pass and report it as failed.
        skip = {name for name, _ in region_failures}
        all_projects.extend(p for p in folder_contents if p.loc_name not in skip)
        update_failed.extend(
            f"{name} (base version update: {reason})"
            for name, reason in region_failures
        )
    logger.info(f"{len(all_projects)} derived project(s) to process")

    ## 3) Run IPStoPF and SystemProtectionAsessmenet wrapper script
    failed_projects = bru.main(app, all_projects)

    ## 4) Run SystemProtectionAsessmenet, with source impedance custom inputs
    ## TODO separate these 2 functions out, so we can play around with the system source impedance inputs (auto/manual)

    ## 5) Change permission to write for all 'Protection Modelling' users
    # bru.main has already recorded which projects were assessed; if
    # this raises that summary is discarded and the
    # run reports EXIT_FATAL instead of EXIT_PARTIAL_FAILURE.
    try:
        change_permissions(app, all_projects)
    except Exception:
        logger.exception(
            "Sharing permissions could not be applied; the mastering "
            "results above are unaffected"
        )

    return len(all_projects) + len(update_failed), update_failed + failed_projects


def str_detect(pf_list, str_dec=r"Protection."):
    ## detect string in powerfactory list, return location indices
    detect_index = []
    for index, each in enumerate(pf_list):
        if re.search(str_dec, str(each)):
            detect_index.append(index)
    return (detect_index)


def create_copies(app, folder_contents, user_folder_path, current_user):
    logger.info("Start create_copies()")
    ## Make copies from master to user
    ## folder_contents : Publisher master projects folder contents
    ## user_folder_path : subfolder in user directory
    ##          (Master Projects - Derived/SEQ Models)
    ## current_user : current_user object
    for ii in range(len(folder_contents)):
        # for ii in range(len(folder_contents)):
        project = folder_contents[ii]
        ## Name of project
        model_name = project.loc_name
        # print(model_name)
        app.SetWriteCacheEnabled(1)
        app.EchoOff()
        try:
            ## Get all versions of project
            versions = project.GetVersions()
            ## Select the latest version to derive
            latest_version = versions[-1]

            ## Check if already exists, if so delete and derive
            dir_options = str_detect(current_user.GetContents(), model_name)
            if dir_options:
                for jj in dir_options:
                    dir_prj = current_user.GetContents()[jj]
                    dir_prj.Delete()

            if str_detect(user_folder_path.GetContents(), model_name):
                # print(" ! copy already exists - skipping")
                nothing = 1
            else:
                ## Create a derived version in user directory
                model_copy = latest_version.CreateDerivedProject(model_name)

                ## Copy into subfolder
                user_folder_path.AddCopy(model_copy)

                ## Delect copy in user directory
                model_copy.Delete()
                # print(" ~ completed")
        except Exception:
                print(f" ! something went wrong with create_copies() for {model_name} - skipping")
                logger.exception(
                    f"create_copies() failed for {model_name} "
                    f"({project.GetClassName()}); skipping"
                )
        finally:
            app.EchoOn()
            app.WriteChangesToDb()
            app.SetWriteCacheEnabled(0)


def get_region_suffix(selected_folder):
    ## Use the selected_folder to determine suffix for folder structure
    if re.search(r"SEQ Models", selected_folder):
        user_suffix = "SEQ Models"
    elif re.search(r"Northern", selected_folder):
        user_suffix = "Regional Models\\Northern"
    elif re.search(r"Southern", selected_folder):
        user_suffix = "Regional Models\\Southern"
    else:
        print("error")
        user_suffix = []
    return user_suffix


def create_region_copies(app, selected_folder, current_user):
    logger.info("Start create_region_copies()")
    ## Get list of all projects in selected folder (from Publisher)
    folder = current_user.GetContents(selected_folder)[0]
    folder_contents = folder.GetContents("*.IntPrj")

    ## Create derived folder structure in user directory if doesn't exist
    check_user_folder_exists(current_user)

    user_suffix = get_region_suffix(selected_folder)
    user_folder_path = current_user.GetContents(f'{USER_DERIVED_MASTER_PROJECT}\\{user_suffix}')[0]

    ## create derived copies of master projects
    create_copies(app, folder_contents, user_folder_path, current_user)  ## slow if all new


def check_user_folder_exists(current_user):
    logger.info("Start check_user_folder_exists()")
    ## Check user folders exist, if not them make them
    user_no_exists = []
    try:
        current_user.GetContents(USER_DERIVED_MASTER_PROJECT)[0]
    except:
        print("user folder doesn't exist")
        user_no_exists = True
        pass

    if user_no_exists:
        try:
            ## Create MasterProjects - Derived subfolder
            current_user.CreateObject("IntFolder", "MasterProjects - Derived")

            ## Create SEQ and Regional Models subfolders
            dir_folder = current_user.GetContents()
            parent = str_detect(dir_folder, "MasterProjects")

            dir_folder[parent[0]].CreateObject("IntFolder", "Regional Models")
            dir_folder[parent[0]].CreateObject("IntFolder", "SEQ Models")

            ## Create Southern and Northern subfolders
            parent_folder = dir_folder[parent[0]].GetContents()
            child = str_detect(parent_folder, "Regional")

            parent_folder[child[0]].CreateObject("IntFolder", "Southern")
            parent_folder[child[0]].CreateObject("IntFolder", "Northern")
            print("created user folder for derived copies")
        except:
            print("user folder doesn't exist and can't be created")
            pass


def _version_name(version):
    """Name of a base version object for the log."""
    return version.loc_name if version else "none"


def update_derived_models(folder_contents, app):
    """
    Bring each derived copy up to the newest base version of its master.

    A project that cannot be read, activated or updated is logged and
    skipped, and the rest of the region still runs. A lost PowerFactory
    session (pf.ExitError) is not caught: nothing after it can work.

    Returns:
        List of (project name, reason) for the projects that failed. The
        caller leaves these out of the fleet pass and reports them.
    """
    logger.info(
        f"Start update_derived_models(): {len(folder_contents)} project(s)"
    )
    region_clock = time.perf_counter()
    failures = []
    attempted = 0
    for project in folder_contents:
        name = "<name unreadable>"
        activated = False
        clock = time.perf_counter()
        try:
            name = project.loc_name
            folder = project.GetParent()
            old_base = _version_name(project.GetAttribute("der_baseversion"))
            ## der_baseversion2 is empty when the copy is already on the
            ## most recent base version
            new_base = project.GetAttribute("der_baseversion2")
            if new_base is None:
                logger.info(f"Base version {name}: up to date ({old_base})")
                continue
            expected = _version_name(new_base)

            if project.Activate():
                raise RuntimeError("Activate() returned an error code")
            activated = True
            attempted += 1
            ## Discard changes in derived version, favour new base version
            return_code = project.UpdateToMostRecentBaseVersion(0, 1, 1)

            # The update replaces the project object, so read the result
            # from the folder, not from the handle taken before it.
            current = folder.GetContents(f"{name}.IntPrj")
            if current:
                now_base = _version_name(
                    current[0].GetAttribute("der_baseversion")
                )
                pending = current[0].GetAttribute("der_baseversion2")
            else:
                now_base, pending = "project not found after update", None
            message = (
                f"Base version {name}: {old_base} -> {now_base} "
                f"(expected {expected}) in "
                f"{time.perf_counter() - clock:.1f} s, "
                f"return code {return_code}"
            )
            if return_code or not current or pending is not None:
                logger.warning(f"{message}; update not confirmed")
            else:
                logger.info(message)
        except pf.ExitError:
            raise
        except Exception as exc:
            logger.exception(
                f"Base version update failed for {name} after "
                f"{time.perf_counter() - clock:.1f} s; project skipped"
            )
            failures.append((name, f"{type(exc).__name__}: {exc}"))
        finally:
            if activated:
                # Must not raise: an exception from a finally block
                # replaces the one already in flight.
                try:
                    active = app.GetActiveProject()
                    if active:
                        active.Deactivate()
                except Exception:
                    logger.warning(
                        f"Could not deactivate {name} after its base "
                        f"version update",
                        exc_info=True,
                    )
    logger.info(
        f"update_derived_models(): {len(folder_contents)} checked, "
        f"{attempted} update(s) attempted, {len(failures)} failed in "
        f"{time.perf_counter() - region_clock:.1f} s"
    )
    return failures


def change_permissions(app, all_projects):
    """Share the project to the selected group

    """
    # selected_group = 'ErgonPublisher'
    selected_group = 'Protection Modelling'

    cur_user = app.GetCurrentUser()
    user_group = cur_user.GetAttribute("fold_id").SearchObject(
        rf"Cnf\Groups\{selected_group}.IntGroup"
    )
    app.SetWriteCacheEnabled(1)
    for project in all_projects:
        logger.info(project)
        project.SetAttributeLength("share_g", 1)
        len_share = project.GetAttributeLength("share_g")
        logger.info(f"Length = {len_share}")
        project.share_g = [user_group]
        logger.info(project.share_g)
        project.SetAttributeLength("share_a", 1)
        project.share_a = [3]
    app.SetWriteCacheEnabled(0)


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
    # user = get_key_from_yaml(d, "user", yaml_ini_file)
    # password = get_key_from_yaml(d, "password", yaml_ini_file)
    # file_dir = get_key_from_yaml(d, "file_dir", yaml_ini_file)
    # ini_file = get_key_from_yaml(d, "ini_file", yaml_ini_file)

    # call_function = f'/ini "{file_dir}\\{ini_file}"'

    safe_load_pf_credentials()

    logger.info(f"Call function is {CALL_FUNCTION}")
    logger.info(f"user is {USER}")

    try:
        app = pf.GetApplicationExt(USER, PASSWORD, CALL_FUNCTION)
    except pf.ExitError:
        logger.exception("Unable to get application")
        raise

    logger.info(f"Opened {app}")

    try:
        yield app
    finally:
        # Teardown must not raise. An exception thrown from a finally
        # block replaces whatever exception is already in flight, so a
        # dead PowerFactory session here masks the real failure.
        try:
            active_project = app.GetActiveProject()
            if active_project:
                active_project.Deactivate()
        except Exception:
            logger.warning(
                "Could not deactivate the active project while closing the "
                "PowerFactory session",
                exc_info=True,
            )


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