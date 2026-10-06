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

    total, failed = workflow(app, SEQ_MASTER_PROJECTS_FULL_NAME)  ## Focus only on Stafford pilot
    # workflow(app, EE_SOUTHERN_MASTER_PROJECTS_FULL_NAME)
    # workflow(app, EE_NORTHERN_MASTER_PROJECTS_FULL_NAME)
    return total, failed


def workflow(app, selected_folder):
    logger.info(f"Start {selected_folder} projects")
    ## Use the selected_folder to determine suffix for folder structure
    user_suffix = get_region_suffix(selected_folder)
    current_user = app.GetCurrentUser()
    user_folder_path = current_user.GetContents(f'{USER_DERIVED_MASTER_PROJECT}\\{user_suffix}')[0]
    folder_contents = user_folder_path.GetContents()[31:33]

    ## 1) Check derived copies exist, if not then create
    create_region_copies(app, selected_folder, current_user)

    ## 2) Check is derived copies are latest version, if not then update to latest
    update_derived_models(folder_contents, app)

    ## TODO ask what this does, was in Dan's original workflow
    app.ReloadProfile()

    ## 3) Run IPStoPF and SystemProtectionAsessmenet wrapper script
    failed_projects = bru.main(app, folder_contents)

    ## 4) Run SystemProtectionAsessmenet, with source impedance custom inputs
    ## TODO separate these 2 functions out, so we can play around with the system source impedance inputs (auto/manual)

    ## 5) Change permission to write for all 'Protection Modelling' users
    # bru.main has already recorded which projects were assessed; if
    # this raises that summary is discarded and the
    # run reports EXIT_FATAL instead of EXIT_PARTIAL_FAILURE.
    try:
        change_permissions(app, folder_contents)
    except Exception:
        logger.exception(
            "Sharing permissions could not be applied; the mastering "
            "results above are unaffected"
        )

    return len(folder_contents), failed_projects


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
        except:
            print(" ! something went wrong with create_copies() - skipping")
            pass
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
    folder_contents = folder.GetContents()

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


def is_new_base_available(ver_obj):
    ## Check is new base version available
    current_ver = ver_obj.GetAttribute('der_baseversion')
    latest_ver = ver_obj.GetAttribute('der_baseversion2')
    if latest_ver == None:
        ## If already most recent then der_baseversion2 is empty
        return False
    else:
        return True


def update_derived_models(folder_contents, app):
    logger.info("Start update_derived_models()")
    ## For each project in user folder
    for ii in range(len(folder_contents)):
        project = folder_contents[ii]
        ## Check is new base version is available, then update
        if is_new_base_available(project):
            ## 1) Get list of derived model changes between current and latest version
            ## TODO redo this code to get more meaningful/high level differences
            # version_changes = get_version_changes(project, app)

            ## 2) Then update model to latest version
            project.Activate()
            ## Discard changes in derived version, favour new base version
            base_update = project.UpdateToMostRecentBaseVersion(0, 1, 1)
            project.Deactivate()


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
