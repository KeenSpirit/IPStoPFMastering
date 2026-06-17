import sys
import logging
import powerfactory as pf
sys.path.append(r'\\ecasd01\WksMgmt\PowerFactory\ScriptsDEV\ReachStudy')
import reach_study as rs
logger = logging.getLogger(__name__)
sys.path.append(r'\\Ecasd01\WksMgmt\PowerFactory\Scripts\pfTextOutputs')
import pftextoutputs
import time
import traceback
import yaml


def run_main():
    app = pf.GetApplication()
    # main(app)

    with pftextoutputs.PowerFactoryLogging(
        pf_app=app,
        add_handler=True,
        handler_level=logging.DEBUG,
        logger_to_use=logger,
        formatter=pftextoutputs.PFFormatter(
            '%(module)s: Line: %(lineno)d: %(message)s'
        ),
    ) as pflogger:
        main(app)
    del app


def main(app):
    """It is required to do multiple reach studies to get information about
    a large network. This script will all the user to select a folder
    containing a bunch of projects and assess them. Becuase multiple machines
    could be running this script will filter out the projects that need the study
    prior to starting."""
    app.ClearOutputWindow()
    project = find_next_project(app)
    while project:
        try:
            logger.info(f"Project being studies is {project}")
            project.Activate()
            study_case = activate_study_case(app, 'Protection_Study')
            if study_case == 'Study Case':
                project.SetAttribute('for_name', 'Failed')
            else:
                reach_study(app, project)
                project.SetAttribute('for_name', 'Complete')
            project.Deactivate()
            project = find_next_project(app)
        except Exception as err:
            project.SetAttribute('for_name', 'Failed to complete')
            unformatted_text = traceback.extract_tb(err.__traceback__)
            text = traceback.format_list(unformatted_text)
            project.SetAttribute('desc', text)
            project.Deactivate()
            project = find_next_project(app)


def activate_grid(app, device, grid_list):
    """Only the grid that is associated with device should be active."""
    # The device might belong to one grid but the network to another.
    sub_name = device.GetAttribute('cpSubstat')
    grid_name = device.GetAttribute('cpGrid')
    poss_grid_name = ['Boundary Subs']
    for pf_obj in [sub_name, grid_name]:
        if pf_obj:
            poss_grid_name.append(pf_obj.loc_name)
    for grid in grid_list:
        if grid.loc_name in poss_grid_name:
            grid.Activate()
        else:
            grid.Deactivate()
    app.Rebuild()


def activate_study_case(app, case_name):
    """The defined case name will be used to searh the list of study cases and
    activate the correct one."""
    study_cases = app.GetProjectFolder('study').GetContents('*.IntCase')
    for study_case in study_cases:
        if case_name == study_case.loc_name:
            active_study_case = study_case.Activate()
            break
    else:
        active_study_case = "Study Case"
    return activate_study_case


def all_relevant_objects(app, folders, type_of_obj, objects=None):
    """When performing a GetContents on objects outside your own user, the function
    can take a significant amount of time. This is a quick function to perform
    a similar type function."""
    for folder in folders:
        if not objects:
            objects = folder.GetContents(type_of_obj, 0)
        else:
            objects += folder.GetContents(type_of_obj, 0)
        sub_folders = folder.GetContents("*.IntFolder", 0)
        sub_folders += folder.GetContents("*.IntPrjfolder", 0)
        if sub_folders:
            objects = all_relevant_objects(app, sub_folders, type_of_obj, objects)
    return objects


def create_folder(app, title, prjt):
    """This function will create a folder under the active project. It will
    also collect key information about the conditions used during this
    instance of running the script."""
    date = time.strftime("%Y%m%d")
    title = f"{date} {title}"
    # Determine if a folder already exists and ask the user how they would
    # like to proceed. If it doesn't exist create the folder.
    reach_results_folder = prjt.GetContents("Reach Study Results.IntFolder")[0]
    contents_of_reach = reach_results_folder.GetContents("*.IntFolder")
    for folder in contents_of_reach:
        if title in folder.loc_name:
            folder.Delete()
    folder = reach_results_folder.CreateObject("IntFolder", title)
    return folder


def find_next_project(app):
    """This will search the folder selected in the script. It will check to
    make sure the project is not locked by another user. If it is not locked
    then check the for_name to see if a study needs to be done."""
    current_script = app.GetCurrentScript()
    folder = current_script.folder
    projects = all_relevant_objects(app, [folder], '*.IntPrj')
    for project in projects:
        # Check to see if it is locked
        locked_by = project.GetAttribute('share_lockingUsers')
        if locked_by == '-':
            # Check to see if the project needs to be studied
            prjt_desc = project.GetAttribute('for_name')
            if prjt_desc == 'Reach':
                return project
    else:
        return None


def get_yaml_d(yaml_ini_file):
    """Get the Yaml Dictionary"""
    with open(yaml_ini_file) as yaml_f:
        d = yaml.load(yaml_f)
    return d


def produce_secured_app_instance():
    """Create an instance of Powerfactory"""
    yaml_ini_file = (r"C:\LocalData\BatchStudy\pf_login.yaml")
    d = get_yaml_d(yaml_ini_file)
    user = d['user']
    password = d['password']
    file_dir = d['file_dir']
    ini_file = d['ini_file']
    call_function = f'"/ini:{file_dir}\\{ini_file}"'
    app = pf.GetApplication(user, password, call_function)
    return app


def reach_study(app, prjt):
    """This function will utilise the master version of the Reach Study script.
    To accomadate speed this script will need to enable and disable grids."""
    # Create a list of grids
    net_dat = app.GetProjectFolder("netdat")
    grid_list = net_dat.GetContents('*.ElmNet')
    for grid in grid_list:
        grid.Activate()
    app.Rebuild()
    # Set all loads out of service
    loads = [load for load in prjt.GetContents("*.ElmLod", True)
             if not load.GetAttribute("e:outserv")]
    for load in loads:
        load.SetAttribute("outserv", 1)
    # Import conductor type database
    material_dict = rs.conductors_properties(app)
    # Set up a database of the active devices in the model
    [devices, device_dict] = rs.prot_device(app)
    # Create a study folder
    study_folder = create_folder(app, "Current State", prjt)
    # Create a fault level dictionary to be used to determine fault location
    term_dict = rs.terminal_dictionary_creation(app, prjt)
    # Create a loop that goes through each selected device
    for i, pf_device in enumerate(devices):
        conduct_type_changed = False
        device = pf_device.loc_name
        prjt.chr_name = device
        activate_grid(app, pf_device, grid_list)
        # Create reach result folder for this device
        folder = rs.create_folder(app, device, study_folder)
        # Create a matrix in the result folder to record the reults
        matrix = rs.matrix_creation(app, folder, device, "Main")
        # Determine the OC, EF and NPS setting for the devices
        setting_values = rs.determine_pickup_values(app, pf_device)
        if not setting_values[0] and not setting_values[1]:
            # This indicates that this device is not configured to perform protection
            matrix.Delete()
            folder.Delete()
            continue
        # Get a list of lines primary protected by this device
        [line_list, line_dict, tripped_devices] = rs.get_primary_protected_lines(
            app, pf_device, prjt, device_dict
        )
        num_trip_dev = len(tripped_devices)
        if num_trip_dev > 1 and not conduct_type_changed:
            # These devices might be a main and backup relay in the same circuit breaker
            cubicles = []
            for tripped_device in tripped_devices:
                cubicle = tripped_device.fold_id.loc_name
                if cubicle not in cubicles:
                    cubicles.append(cubicle)
            if len(cubicles) > 1:
                # If the project contains sequential tripping then set a conductor
                # type per line segment
                [variation, temp_lib] = rs.configure_project(app, prjt)
                conduct_type_changed = True
        # Create a list of all the used conductor types
        used_cond_types = rs.prj_cond_details(app, prjt)
        # Get the backup device
        if pf_device.GetClassName() == "ElmRelay":
            bckup_dev = rs.get_backup_device(app, pf_device, tripped_devices)
        else:
            bckup_dev = pf_device
        if bckup_dev and bckup_dev.GetClassName() == "ElmRelay":
            # Create a folder for the device that is providing backup or
            # return the folder that already exists
            bckup_folder = rs.create_folder(app, bckup_dev.loc_name, study_folder)
            # Create a matrix in the result folder to record the reults
            bckup_matrix = rs.matrix_creation(app, bckup_folder, device, "Backup")
            # Determine the OC, EF and NPS setting for the devices
            bckup_setting_values = rs.determine_pickup_values(app, bckup_dev)
        for row_num, line_name in enumerate(line_list):
            line = line_dict[line_name]
            # Study each line and record the results in a matrix
            rs.update_matrix(app, matrix, row_num, line, num_trip_dev, setting_values)
            app.SetGuiUpdateEnabled(1)
            app.ClearOutputWindow()
            logger.info(f"Device {device} is {i+1} of {len(devices)}.")
            logger.info(
                f"{line} number {row_num+1} or {len(line_list)} is being studied"
            )
            app.SetGuiUpdateEnabled(0)
            [fault_location, no_of_ends] = rs.get_fault_location(app, line, term_dict)
            if no_of_ends == 1:
                fault_impedance = [line.GetAttribute("e:R1"), line.GetAttribute("e:X1")]
            else:
                fault_impedance = [0, 0]
            # Calculate the temperatures for the conductors impacting the
            # fault path
            fault_cleared = rs.cond_temp_correction(app, fault_location, line,
                                                    used_cond_types,
                                                    device_dict, material_dict,
                                                    fault_impedance, no_of_ends)
            # If the fault has failed to be cleared means that the temperatures
            # could not be calculated. Therefore reach is not calculated
            if not fault_cleared:
                continue
            try:
                matrix.Set(
                    row_num + 1, 12, round(line.GetAttribute("r:pCondCir:e:rtemp"), 2)
                )
            except AttributeError:
                pass
            # Some relays are only used to detect EFs. These should only be studied
            # for this type of fault
            if setting_values[0] > 0:
                # Execute a L-L fault study
                rs.ph_fault(app, matrix, row_num, num_trip_dev, pf_device,
                        fault_location, line, fault_impedance)
            # Execute a L-G study
            rs.ef_fault(app, matrix, row_num, num_trip_dev, pf_device,
                        fault_location, line, fault_impedance)
            # Perform the backup study for the line. Turn the primary protection
            # device out of service
            if bckup_dev and bckup_dev.GetClassName() == "ElmRelay":
                rs.update_matrix(
                    app, bckup_matrix, row_num, line, num_trip_dev, bckup_setting_values
                )
                pf_device.SetAttribute("e:outserv", 1)
                # Calculate the temperatures for the conductors impacting
                # the fault path
                if no_of_ends == 1:
                    fault_impedance = [line.GetAttribute("e:R1"),
                                       line.GetAttribute("e:X1")]
                else:
                    fault_impedance = [0, 0]
                fault_cleared = rs.cond_temp_correction(app, fault_location,
                                                        line, used_cond_types,
                                                        device_dict,
                                                        material_dict,
                                                        fault_impedance,
                                                        no_of_ends)
                # If the fault has failed to be cleared means that the
                # temperatures could not be calculated. Therefore reach is not
                # calculated
                if not fault_cleared:
                    continue
                try:
                    bckup_matrix.Set(row_num + 1, 12,
                                     round(line.GetAttribute("r:pCondCir:e:rtemp"), 2))
                except AttributeError:
                    pass
                # Some relays are only used to detect EFs. These should only be studied
                # for this type of fault
                if bckup_setting_values[0] > 0:
                    # Execute a L-L fault study
                    rs.ph_fault(app, bckup_matrix, row_num, num_trip_dev,
                                bckup_dev, fault_location, line, fault_impedance)
                # Execute a L-G study
                rs.ef_fault(app, bckup_matrix, row_num, num_trip_dev,
                            bckup_dev, fault_location, line, fault_impedance)
                pf_device.SetAttribute("e:outserv", 0)
        if bckup_dev and bckup_dev.loc_name == device:
            bck_mat = folder.AddCopy(matrix, f"Backup - {device}")
            bck_mat.Save()
        matrix.Save()
        if bckup_dev and bckup_dev.GetClassName() == "ElmRelay":
            bckup_matrix.Save()
        if conduct_type_changed:
            variation.Deactivate()
            variation.Delete()
            temp_lib.Delete()
    for load in loads:
        load.SetAttribute("outserv", 0)
    app.EchoOn()


if __name__ == '__main__':
    run_main()
