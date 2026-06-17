import sys

sys.path.append(r"\\ecasd01\WksMgmt\PowerFactory\ScriptsLIB\NetDash-Reader")
from netdashread import get_json_data
from tenacity import retry
from tenacity import stop_after_attempt, wait_random_exponential

sys.path.append(r"\\ecasd01\WksMgmt\PowerFactory\ScriptsLIB\AssetClasses")
from assetclasses.corporate_data import get_cached_data


def main():
    print("Updating the Energex Setting ID Cache")
    rows = cached_data("Report-Cache-ProtectionSettingIDs-EX")
    print("Updating the Ergon Setting ID Cache")
    rows = cached_data("Report-Cache-ProtectionSettingIDs-EE")
    print("Updating the Ergon IT data Cache")
    rows = cached_data("Report-Cache-ProtectionITSettings-EE")
    print("Updating the Energex IT data Cache")
    rows = cached_data("Report-Cache-ProtectionITSettings-EX")


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_random_exponential(multiplier=1, max=5),
)
def cached_data(report):
    """This retrieves the IPS data from NetDash"""
    rows = get_cached_data(report, max_age=10, recache=True)
    for i, row in enumerate(rows):
        if i == 10:
            break
    return rows


if __name__ == "__main__":
    main()
