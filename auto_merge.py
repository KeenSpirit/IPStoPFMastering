import powerfactory as pf
import sys


def main(app):
    """The intent of this script is to merge the protection users derived
    data base for the area models with the Publisher"""
    app.ClearOutputWindow()
    current_user = app.GetCurrentUser()
    current_script = app.GetCurrentScript()
    folder = current_script.folder
    app.PrintInfo(folder)
    all_projects = all_relevant_objects([folder], '*.IntPrj')
    for i, project in enumerate(all_projects):
        app.ClearOutputWindow()
        app.PrintInfo(f"{project} is {i} of {len(all_projects)}")
        if project.GetAttribute('e:der_baseversion2'):
            merge_project(app, project, current_user)
    # Set
    

def merge_project(app, project, current_user):
    """This function will merge with the latest base version. It will take the
    base version as the preferred"""
    name = project.loc_name
    # First rename the project
    project.loc_name = f"{name}_delete"
    # Create a new project in the same location as the exiting
    folder = project.fold_id
    base_project_ver = project.der_baseproject.GetLatestVersion(0)
    new_prjt = base_project_ver.CreateDerivedProject(f'{name}', folder)
    # Merge the project to be deleted and the newly derived project
    com_merge = current_user.CreateObject("ComMerge", "MergeVersionToDerived")
    app.SetWriteCacheEnabled(1)
    com_merge.SetAttribute('top_base', new_prjt)
    com_merge.SetAttribute('name_base', 'project_to_be_updated')
    com_merge.SetAttribute('top_mod1', project)
    com_merge.SetAttribute('name_mod1', 'source_project')
    com_merge.iopt_3way = 0
    com_merge.merge = 2
    app.WriteChangesToDb()
    com_merge.Compare()
    com_merge.SetAutoAssignmentForAll(2)
    com_merge.Merge(1)
    app.WriteChangesToDb()
    app.SetWriteCacheEnabled(0)
    project.Delete()


def all_relevant_objects(folders, type_of_obj, objects=None):
    """When performing a GetContents on objects outside your own user, the function
    can take a significant amount of time. This is a quick function to perform
    a similar type function."""
    for folder in folders:
        if not objects:
            objects = folder.GetContents(type_of_obj)
        else:
            objects += folder.GetContents(type_of_obj)
        sub_folders = folder.GetContents('*.IntFolder')
        sub_folders += folder.GetContents('*.IntPrjfolder')
        if sub_folders:
            objects = all_relevant_objects(sub_folders, type_of_obj, objects)
    return objects


if __name__ == '__main__':
    app = pf.GetApplication()
    main(app)