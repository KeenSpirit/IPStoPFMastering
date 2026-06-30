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

logger = logging.getLogger(__name__)

# logging.basicConfig(level=logging.DEBUG)
std_out_handler = logging.StreamHandler(sys.stdout)
std_out_handler.setLevel(logging.DEBUG)
std_out_handler.setFormatter(
    logging.Formatter("%(asctime)s: %(filename)s: %(lineno)d:\t%(message)s")
)
logger = logging.getLogger(__name__)
# TODO remove std out logging once email logging is working
logger.setLevel(logging.DEBUG)
logger.addHandler(std_out_handler)

root_logger = logging.getLogger()
root_logger.setLevel(logging.DEBUG)
root_logger.addHandler(std_out_handler)

# Ensure app loggers stay at INFO so their records reach the stdout handler on root
for name in ("ips_data", "update_powerfactory", "config", "core", "utils", "logging_config"):
    logging.getLogger(name).setLevel(logging.INFO)


def run_main():
    yaml_ini_file = r"Y:\PROTECTION\STAFF\Dan Park\PowerFactory\Dan script development\IPStoPFMastering\pf_login.yaml"
    d = get_yaml_d(yaml_ini_file)
    import_required_pf_modules()

    with produce_secured_app_instance(d, yaml_ini_file, logger=logger) as app:
        if app is None:
            print("Instance is NONE")
            return
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
            main(app)


def main(app):
    """ Pilot projects:
    Atherton
    Mossman
    Postmans Ridge
    Clayfield
    """
    app.ClearOutputWindow()
    all_projects = derive_latest_versions(app, pilot="Nudgee")
    app.ReloadProfile()
    bru.main(app, all_projects)
    change_permissions(app, all_projects)


def change_permissions(app, all_projects):
    """Share the project to the Ergon Publisher"""
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


def derive_latest_versions(app, pilot=False):
    """The master folder is located under the publisher. The IPS to PF will only
    update models whos parent folder is:
        - Northern
        - Southern
        - SEQ Models
    This function will derive the latest version of all projects under these folders.
    To test on a single project, the name of the project is passed as pilot (str).
    """
    app.SetWriteCacheEnabled(1)
    app.EchoOff()
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
        master_projects = [project for project in master_projects if project.loc_name == pilot]
    projects = []
    for i, project in enumerate(master_projects):
        if i % 10 == 0:
            print(f"{i} projects have been derived")
        prjt_ver = project.GetLatestVersion(0)
        if not prjt_ver:
            print(f"project - {project} does not have a version")
            continue
        projects.append(
            prjt_ver.CreateDerivedProject(f"{project.loc_name}", derive_location)
        )
    app.EchoOn()
    app.WriteChangesToDb()
    app.SetWriteCacheEnabled(0)
    return projects


def derive_test_project(app):
    """ Pilot projects:
    Atherton
    Mossman
    Postmans Ridge
    Clayfield
    """



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
        logger.error("Unable to get application")
        root_logger.error("Unable to get application")
        root_logger.exception("Unable to get application")
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
    run_main()
