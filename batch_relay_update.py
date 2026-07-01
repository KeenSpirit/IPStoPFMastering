import powerfactory as pf
import time
import sys

sys.path.append(r"\\ntgcca1\ntdpe\PROTECTION\STAFF\Dan Park\PowerFactory\Dan script development\IPStoPF")
import main as ips_to_pf
sys.path.append(r"\\ntgcca1\ntdpe\PROTECTION\STAFF\Dan Park\PowerFactory\Dan script development\SystemProtectionAssessment")
import start

def main(app=None, all_projects=None):
    """Update all relays in a project"""
    if not app:
        app = pf.GetApplication()
    # All the folders under this folder needs the relays updated
    if not all_projects:
        current_script = app.GetCurrentScript()
        projects_folder = current_script.object_to_update
        all_projects = all_relevant_objects([projects_folder], "*.IntPrj")

    """ Try to solve problem with opening projects"""
    # Figure out if we can skip broken sites
    print("Testing files to see if they open")
    project_open = []
    project_didnot_open = []
    for i, project in enumerate(all_projects):
        print(
            "Project {} is {} of {} is being worked on".format(
                project, i + 1, len(all_projects)
            )
        )

        # Deactivate TRY and EXCEPT when PF problem is fixed
        try:
            # test each file to see if it opens
            project.Activate()
            prjt = app.GetActiveProject()
            file_name = prjt.loc_name.replace("/", "_")
            project_open.append(project)
        except AttributeError:
            # Attribute error
            project_didnot_open.append(project)
    print(project_didnot_open)
    all_projects = project_open
    """ Finished"""

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
        # app.SetGuiUpdateEnabled(0)
        project.Activate()
        time.sleep(5)
        net_mod = app.GetProjectFolder("netmod")
        app.ClearOutputWindow()
        ips_to_pf.main(app, True)
        new_version = create_version(project, f'{time.strftime("%Y%m%d")} IPS Import')
        start.begin(app)
    project.Deactivate()


def create_version(project, name):
    """Create a new version in the given project with the name supplied"""
    if (
        project
        and isinstance(project, pf.DataObject)
        and project.GetClassName() == "IntPrj"
    ):
        new_version = project.CreateVersion()
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