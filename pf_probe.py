"""Minimal PowerFactory engine-mode probe. Writes one line per attempt."""
import sys, os, yaml
from pathlib import Path
from datetime import datetime

PF_PYTHON_DIR = r"C:\Program Files\DIgSILENT\PowerFactory 2025 SP3\Python\3.12"
PF_INSTALL_DIR = str(Path(PF_PYTHON_DIR).parents[1])
YAML_DIR = r"C:\LocalData\ProtectionBatchRunner"
LOG = r"C:\LocalData\ProtectionBatchRunner\pf_probe.log"

def log(msg):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now().isoformat()}\t{msg}\n")

app = None
try:
    os.add_dll_directory(PF_INSTALL_DIR)
    sys.path.append(PF_PYTHON_DIR)
    import powerfactory as pf
    with open(os.path.join(YAML_DIR, "pf_login.yaml")) as fh:
        d = yaml.safe_load(fh)
    call = f'/ini "{d["file_dir"]}\\{d["ini_file"]}"'
    log(f"SESSIONNAME={os.environ.get('SESSIONNAME')}")
    log(f"USERPROFILE={os.environ.get('USERPROFILE')}")
    log(f"APPDATA={os.environ.get('APPDATA')}")
    log(f"LOCALAPPDATA={os.environ.get('LOCALAPPDATA')}")
    pf_cfg = Path(os.environ.get('LOCALAPPDATA', '')) / "DIgSILENT"
    log(f"PF user config dir exists: {pf_cfg.exists()} -> {pf_cfg}")
    ini = Path(d['file_dir']) / d['ini_file']
    log(f"ini exists: {ini.exists()} -> {ini}")
    log(f"share reachable: {os.path.isdir(r'\\ecasd01\WksMgmt')}")
    log("attempting GetApplicationExt")
    app = pf.GetApplicationExt(d["user"], d["password"], call)
    log("SUCCESS - licence acquired")
except Exception as e:
    log(f"FAILED - {type(e).__name__}: {e}")
finally:
    if app:
        del app        # release the licence