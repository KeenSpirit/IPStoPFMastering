import powerfactory as pf


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

    app.SetShowAllUsers(1)
    all_users = app.GetAllUsers()
    for user in all_users:
        if user.loc_name == 'Protection':
            break
    master_derived_folder = user.GetContents('MasterProjects - Derived')[0]
    derived_folders = master_derived_folder.GetContents("*.IntFolder")

    projects = []
    app.SetWriteCacheEnabled(1)
    app.EchoOff()

    try:
        for project in master_projects:
            region_fold = project.GetParent()
            if region_fold not in derived_folders:
                derive_folder = master_derived_folder.CreateObject("IntFolder", region_fold.loc_name)
                derived = create_derived(project, derive_folder)
                if derived is not None:
                    projects.append(derived)
            else:
                derive_folder = master_derived_folder.GetContents(f"{region_fold.loc_name}.IntFolder")[0]
                if project not in derive_folder:
                    derived = create_derived(project, derive_folder)
                    if derived is not None:
                        projects.append(derived)
                else:
                    derived = derive_folder.GetContents(f"{project.loc_name}.IntPrj")[0]
                    if derived.der_baseversion2 is None:
                        derived.Delete()
                        derived = create_derived(project, derive_folder)
                        if derived is not None:
                            projects.append(derived)
                    else:
                        projects.append(derived)
    finally:
        app.EchoOn()
        app.WriteChangesToDb()
        app.SetWriteCacheEnabled(0)

    return projects


def create_derived(project, derive_folder):
    prjt_ver = project.GetLatestVersion(0)
    if not prjt_ver:
        logger.warning(f"{project.loc_name} has no version; skipping")
        return None
    derived = prjt_ver.CreateDerivedProject(
        f"{project.loc_name}", derive_folder
    )
    if not derived:
        logger.warning(
            f"CreateDerivedProject failed for {project.loc_name}; skipping"
        )
        return None
    return derived


if __name__ == "__main__":

    app = pf.GetApplication()
    projects = derive_latest_versions(app)
    app.PrintPlain("projects:")
    for project in all_projects:
        app.PrintPlain(project)