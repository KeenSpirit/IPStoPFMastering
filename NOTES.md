Setting up the script:

PowerFactory login credentials are stored in a .yaml file. In the run_main() function, the yaml_ini_file variable needs to be specified according to the path of the .yaml file. 
The ips_to_pf_mastering.py module will call the batch_relay_update.py module. In the latter module, you need to append the path of the IPStoPF script you intend to run. 

In order to import the powerfactory library, you have to append the path to the library that is associated with the interpreter you’re actually launching with. 
Firstly, check which version of python you’re launching with. Type the following in to the command prompt:
python -c "import sys; print(sys.version); print(sys.maxsize > 2**32)"

Now make sure your PowerFactory directory matches that version of python. For example, if your interpreter is 3.12.3, you would create a directory as such:
PF_PYTHON_DIR = r"C:\Program Files\DIgSILENT\PowerFactory 2025 SP3\Python\3.12"

Running the script:

In the Command Prompt, navigate to the location of your script. Example command:
cd /d Y:\PROTECTION\STAFF\Dan Park\PowerFactory\Dan script development\IPStoPFMastering

The /d is used for switching to a drive letter other than the one you’re currently on.

After the path is updated, type the following:
python {script}.py
Where {script} is the executable file. 
