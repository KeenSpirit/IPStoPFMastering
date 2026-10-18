"""
Dashboard project identity.

The Power BI dashboard keys every fact file and manifest row by project
name. Two projects in different region folders can share a name -
Gympie exists under SEQ Models and under Regional Models/Southern.

A shared name is qualified with its region label, e.g.
"Gympie (SEQ)" and "Gympie (Southern)". Every other project keeps its
plain name, so dashboard history for those projects is unaffected.

Pure module: no PowerFactory access, so it is testable offline.
"""

import logging
from collections import Counter
from typing import Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Names known to exist in more than one region folder. Qualified on
# every run, including partial runs that contain only one of them, so a
# project's dashboard name never depends on which projects ran
# alongside it. Add a name here when a fleet run logs it as a new
# duplicate.
KNOWN_DUPLICATE_NAMES = frozenset({"Gympie"})

# Region folder (the derived project's parent) -> label used in the
# qualified name. Folders not listed use their own name.
REGION_LABELS = {
    "SEQ Models": "SEQ",
}


def region_label(folder: Optional[str]) -> Optional[str]:
    """
    Short region label for a project's parent folder name.

    Args:
        folder: Parent folder name, e.g. 'SEQ Models' or 'Southern'.

    Returns:
        The label, or None when the folder is unknown.
    """
    if not folder:
        return None
    return REGION_LABELS.get(folder, folder)


def dashboard_names(projects: Iterable[Tuple[str, Optional[str]]]) -> List[str]:
    """
    Dashboard names for a run's projects, in the same order.

    A name is qualified with its region label when it appears more than
    once in this run or is in KNOWN_DUPLICATE_NAMES. A duplicate found
    in the run but missing from KNOWN_DUPLICATE_NAMES is logged, since
    a later partial run would otherwise name it differently.

    Args:
        projects: (project name, parent folder name) pairs. The folder
            may be None when it could not be read.

    Returns:
        One dashboard name per project. If two projects would still
        collide (same name, same or unreadable folder), the later ones
        get a numeric suffix so no key is ever shared.
    """
    pairs = [(str(name), folder) for name, folder in projects]
    counts = Counter(name for name, _ in pairs)

    for name, n in counts.items():
        if n > 1 and name not in KNOWN_DUPLICATE_NAMES:
            logger.warning(
                "Project name %r appears %d times in this run; qualified "
                "with its region for the dashboard. Add it to "
                "dashboard_identity.KNOWN_DUPLICATE_NAMES so partial runs "
                "name it the same way.", name, n,
            )

    names: List[str] = []
    for name, folder in pairs:
        label = region_label(folder)
        if (counts[name] > 1 or name in KNOWN_DUPLICATE_NAMES) and label:
            names.append(f"{name} ({label})")
        else:
            names.append(name)

    # Last resort: never emit the same key twice.
    seen: Counter = Counter()
    unique: List[str] = []
    for name in names:
        seen[name] += 1
        unique.append(name if seen[name] == 1 else f"{name} #{seen[name]}")
        if seen[name] == 2:
            logger.warning(
                "Dashboard name %r still not unique after region "
                "qualification; numeric suffixes added", name,
            )
    return unique