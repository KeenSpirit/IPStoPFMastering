IPSDataTransferMastering
===============

This script is used by the publisher to transfer data from IPS to PowerFactory on a weekly bases. It will use the general IPS to PF script to do the transfer.

Open a virtual machine, I would recommend SOEV01948. The reason for this is because it has been set up to complete this task. This includes:
•	C:\LocalData\BatchStudy\pf_login.yaml 
                    This yaml file contains the login details for the ProtectionCentralVM user
•	C:\LocalData\BatchStudy\sql_login_details.yaml
       This yaml file contains login details for accessing both SEQ and Ergon ODS tables. Presently    has Luke Napier details.

Open the python IDLE (Python 3.6 64-bit)
In this software is where you will run the batch script to import IPS data into all models. To do this open:
•	\\ecasd01\WksMgmt\PowerFactory\ScriptsDEV\ProtectionUser\ips_to_pf_mastering.py

Hit Run on this script. This script will use the ips_to_pf.py file slightly different. The biggest time component for the ips_to pf script is everytime it has to query the data base through netdash.
As a user with more previleges we are able to bypass Netdash and hit the ODS data base direct. A limitation of netdash is that it can not filter based on a list. The direct access approach does, this means that you reduce the number of queries {how ever many devices are in the project} to a single query.

The resultant of this script will now be indvidual csv files with the result of the attempted merge between IPS to PF. The folder location for this:
\\ecasd01\WksMgmt\PowerFactory\ScriptsDEV\IPSDataTransferMastering\Script_Results 
This file location is determined by the ips_to_pf.py

The data in each csv file describes the result for each protection device in the project. This includes Relays, recloser, line fuses and Distribution Transformer fuses.
This data is raw and by using Jupyter usefull information has been collated into a report. Open up Jupyter and locate the latest script. At the time of writing this it was called PowerFactory_Relay_Data_V2.

This script imports all these files plus some additional sheets. You can either map the file location above or you can copy those files to somewhere else. Either way in the script you need to correctly map the choosen location.

You should have also mapped where you want the PF_RELAY_DATA.xlsx file to be saved.

Once you have corrected all of the file locations then you are ready to run the script.

The main tab is the Mapping Issues tab. This tab contains information about what work is required. Effectively if there is a setting IPS that needs to be transferred to PowerFactory but it doesn’t know how to do it.

The RELAY_PATTERN column is the the Relay Parameter Pattern in IPS for the setting node.
PATTERN_COUNT is how many settings in IPS has this Relay Parameter Pattern
EXAMPLE_PLANT_NUMBER is used during the development of the relay mapping file.
EXAMPLE_PROJECT is the project that contains this device. Useful for finding th device during development
