#PYTHON ADDITIONAL MODULES
import sys
import logging
import datetime
import time
#Import the powerfactory model to all the script to run external
sys.path.append(r"C:\Program Files\DIgSILENT\PowerFactory 2018 SP3\Python\3.6")
import powerfactory as pf
import yaml
import smtplib
from email.mime.multipart import MIMEMultipart 
from email.mime.text import MIMEText
from email.mime.nonmultipart import MIMENonMultipart
from email.mime.base import MIMEBase
from email import encoders
import batch_relay_update as bru
import glob
import os
import re
import pandas as pd
sys.path.append(r'\\ecasd01\WksMgmt\PowerFactory\ScriptsDEV')
import xlsxwriter


def main():
    """This program is used to continuously search for projects that require
    studies that need a special licence"""
    start_time = time.strftime("%H:%M:%S")
    app = produce_secured_app_instance()
    #app = pf.GetApplication()
    current_user = app.GetCurrentUser()
    app.SetShowAllUsers(1)
    all_users = app.GetAllUsers()
    for user in all_users:
        if user.loc_name == 'Protection':
            break
    # master_derived_folder = user.GetContents('1. MasterProjects - Derived')
    master_derived_folder = user.GetContents('1. MasterProjects - Derived')
    all_projects = all_relevant_objects(master_derived_folder, '*.IntPrj')
    if not all_projects:
        return
    check_project_version(app, all_projects)
    relay_setting_check(app, all_projects)
    stop_time = time.strftime("%H:%M:%S")
    print('Script started at {} and finshed at {}'.format(start_time,
                                                                  stop_time))
    app.PrintInfo('Script started at {} and finshed at {}'.format(start_time,
                                                                  stop_time))
                                                                  
    
def relay_setting_check(app, all_projects):
    """This will check IPS settings against the PowerFactory Settings. It 
    will create a report highlighting the differences between the two
    systems"""
    bru.main(app, all_projects)
    # relay_data_mining()
  

def relay_data_mining():
    """The batch relay setting will create a csv for each project. This
    function is used to report on the progress of the data"""
    # Create a data_frame with data from CSVs for each project
    devices_df = pd.DataFrame()
    location = "C:\\Users\\lnapier\\OneDrive - EnergyQ Online\\Script Outputs\\Relay Data Mining\\Raw Data\\*.csv"
    for file in glob.glob(location):
        temp_df = pd.read_csv(file)
        temp_df['PROJECT'] = file.split('\\')[-1].split('.')[0]
        devices_df = devices_df.append(temp_df, ignore_index =True)
    devices_df.columns = devices_df.columns.str.replace(' ', '_')
    devices_df.fillna(0,inplace = True)
    devices_df = devices_df[devices_df['PLANT_NUMBER'] != 0]
    devices_df = devices_df.drop(devices_df[devices_df['PLANT_NUMBER'].str.contains('\(1\)')].index)
    # Associate each entry to a specific region
    location = 'C:\\Users\\lnapier\\OneDrive - EnergyQ Online\\Script Outputs\\Relay Data Mining\\Additional Sheets\\associated_region.csv'
    devices_df = devices_df.merge(pd.read_csv(location, low_memory = False),
                                  how='left',
                                  left_on='PROJECT',
                                  right_on='POWERFACTORY_ID')
    del devices_df['POWERFACTORY_ID']
    devices_df.drop_duplicates(subset='PLANT_NUMBER', keep='first', inplace=True)
    # Import the sheets that contain feedback
    feedback_df = pd.DataFrame()
    location = "C:\\Users\\lnapier\\OneDrive - EnergyQ Online\\Script Outputs\\Relay Data Mining\\Feedback\\*.csv"
    for file in glob.glob(location):
        feedback_df = feedback_df.append(pd.read_csv(file, usecols = ['PLANT_NUMBER','NEEDED', 'FEEDBACK']), ignore_index = True)
    feedback_df = feedback_df[['PLANT_NUMBER','NEEDED', 'FEEDBACK']]
    devices_df = devices_df.merge(feedback_df, how='left', left_on='PLANT_NUMBER', right_on='PLANT_NUMBER')
    devices_df.fillna('UNKNOWN', inplace=True)
    # If the feedback is that the device should be ignored then they should be removed from the analysis
    devices_df = devices_df[devices_df.NEEDED != 'NO']
    # Associate each device with their type and create a new column
    devices_df['TYPE'] = 'UNKNOWN'
    devices_df.loc[devices_df.PLANT_NUMBER.str.contains('GS-'), 'TYPE'] = 'GAS SWITCH'
    devices_df.loc[devices_df.PLANT_NUMBER.str.contains('RC-'), 'TYPE'] = 'RECLOSER'
    devices_df.loc[devices_df.PLANT_NUMBER.str.startswith('X'), 'TYPE'] = 'RECLOSER'
    devices_df.loc[(devices_df.RELAY_PATTERN.str.contains('Fuse',na=False)) & (devices_df.REGION == 'South_East'), 'TYPE'] = 'LINE_FUSE'
    devices_df.loc[(devices_df.PLANT_NUMBER.str.contains('DO-'))&(devices_df.FUSE_TYPE == 'Line Fuse'), 'TYPE'] = 'LINE_FUSE'
    devices_df.loc[(devices_df.PLANT_NUMBER.str.contains('DO-'))&(devices_df.FUSE_TYPE != 'Line Fuse'), 'TYPE'] = 'TX_FUSE'
    devices_df.loc[devices_df.PLANT_NUMBER.str.contains('SS-'), 'TYPE'] = 'RELAY'
    devices_df.loc[(devices_df.TYPE == 'UNKNOWN') & (devices_df.REGION == 'South_East'), 'TYPE'] = 'RELAY'
    # Define if the device is ok or not
    failed_transfer_result = ['FAILED FUSE', 'Multi Relay', 'Not been mapped', 'Not in IPS', 'Script Failed',
                         'Type Matching Error',' Unable to find the appropriate type']
    devices_df['HEALTH'] = 'OK'
    devices_df.loc[devices_df.RESULT.isin(failed_transfer_result), 'HEALTH'] = 'NOK'
    # Create a count and percentage of failed transfers
    # Overall Health summary
    devices_df['TOTAL'] = devices_df.groupby(['TYPE'])['PLANT_NUMBER'].transform('count')
    devices_df['PERC_FAILED'] = round(100*(devices_df[devices_df.HEALTH == 'NOK'].groupby(['TYPE'])['PLANT_NUMBER'].transform('count')/devices_df.TOTAL),0)
    # Region Health summary
    devices_df['REG_TOTAL'] = devices_df.groupby(['REGION', 'TYPE'])['PLANT_NUMBER'].transform('count')
    devices_df['REG_PERC_FAILED'] = round(100*(devices_df[devices_df.HEALTH == 'NOK'].groupby(['REGION', 'TYPE'])['PLANT_NUMBER'].transform('count')/devices_df.REG_TOTAL),0)
    # Project Health summary
    devices_df['PROJ_TOTAL'] = devices_df.groupby(['REGION', 'PROJECT', 'TYPE'])['PLANT_NUMBER'].transform('count')
    devices_df['PROJ_PERC_FAILED'] = round(100*(devices_df[devices_df.HEALTH == 'NOK'].groupby(['REGION', 'PROJECT', 'TYPE'])['PLANT_NUMBER'].transform('count')/devices_df.PROJ_TOTAL),0)
    # Substation Summary
    devices_df['SUB_TOTAL'] = devices_df.groupby(['REGION', 'PROJECT', 'SUBSTATION','TYPE'])['PLANT_NUMBER'].transform('count')
    devices_df['SUB_PERC_FAILED'] = round(100*(devices_df[devices_df.HEALTH == 'NOK'].groupby(['REGION', 'PROJECT', 'SUBSTATION','TYPE'])['PLANT_NUMBER'].transform('count')/devices_df.SUB_TOTAL),0)
    devices_df.fillna(0,inplace = True)
    # Create files with the respective data frame
    file = r'C:\Users\lnapier\OneDrive - EnergyQ Online\Script Outputs\Relay Data Mining\Result CSVs\{} PF_RELAY_DATA.xlsx'.format(time.strftime("%Y%m%d"))
    # Create the xlsx writer object
    writer = pd.ExcelWriter(file, engine='xlsxwriter')
    # Create a data frame summarising the state of each substation
    summary_df = devices_df.groupby(['TYPE','TOTAL'])['PERC_FAILED'].max()
    summary_df.to_excel(writer, sheet_name='Summary')
    reg_summary_df = devices_df.groupby(['REGION','TYPE','REG_TOTAL'])['REG_PERC_FAILED'].max()
    reg_summary_df.to_excel(writer, sheet_name='Regional Summary')
    proj_summary_df = devices_df.groupby(['REGION', 'PROJECT', 'TYPE','PROJ_TOTAL'])['PROJ_PERC_FAILED'].max()
    proj_summary_df.to_excel(writer, sheet_name='Project Summary')
    sub_summary_df = devices_df.groupby(['REGION', 'PROJECT', 'SUBSTATION','TYPE','SUB_TOTAL'])['SUB_PERC_FAILED'].max()
    sub_summary_df.to_excel(writer, sheet_name='Substation Summary')
    # Create sheets with the missing IPS Data for each region
    for region in ['Northern', 'Southern']:
        # Create an new progress summary sheet for each region
        missing_sheet_name = '{} Missing IPS Data'.format(region)
        missing_df = devices_df[(devices_df.REGION == region)&(devices_df['RESULT'].str.contains('Not in IPS')==True)].reset_index()
        missing_df = missing_df[['SUBSTATION', 'PLANT_NUMBER', 'FEEDBACK']]
        missing_df.to_excel(writer,sheet_name=missing_sheet_name, index=False)
        missing_worksheet = writer.sheets[missing_sheet_name]
        missing_worksheet.set_column('A:B',20,None)
        missing_worksheet.set_column('C:C',100,None)
    # Missing Mapping sheet
    mapping_issues_df = devices_df[devices_df.RESULT == 'Not been mapped'][['PLANT_NUMBER','RELAY_PATTERN']]
    mapping_issues_df.drop_duplicates(subset='RELAY_PATTERN', keep = 'first', inplace = True)
    mapping_issues_df.reset_index(drop=True)
    mapping_issues_df.to_excel(writer, sheet_name='Mapping Issues', index=False) 
    
    writer.save()
    return


def check_project_version(app, all_projects):
    """This function will go through all projects and compare to the master
    project. If the project is not upto date then an email will be sent
    to the SME to address the changes."""
    list_of_projects = list()
    for project in all_projects:
        if project.GetAttribute('e:der_baseversion2'):
            list_of_projects.append(project.loc_name)
    if list_of_projects:
        string_to_be_sent = ('The projects under the Protection User Folder '
                         '"Master Projects EO- Derived" have been checked to '
                         'determine if there is a later version. The following '
                         'projects have been identified as requiring updating:')
        for project in list_of_projects:
            string_to_be_sent += '\n    - {}\n'.format(project)    
        string_to_be_sent += ('\n\n A member of the Protection User group will need '
                              'to perform the merge process \n')
        subject = 'PowerFactory ALERT: Projects that need to be updated'
        send_email(app, string_to_be_sent, subject)
        print('Sending Email')


def send_email(app, body, subject, attachments = None, file_names = None):
    """An email will be sent to relevant people to alert them of the 
    changes."""
    TO_ADDRESS = ['luke.napier@energyq.com.au']#, 'rob.coggan@energyq.com.au', 'paul.millers@energyq.com.au']
    FROM_ADDRESS = TO_ADDRESS[0]
    server = smtplib.SMTP('webmail.services.local')
    msg = MIMEMultipart()
    msg['From'] = FROM_ADDRESS
    msg['To'] = ", ".join(TO_ADDRESS)
    msg['Subject'] = subject
    msg.attach(MIMEText(body,'plain'))
    
    if attachments:
        for i, attachment in enumerate(attachments):
            part = MIMEBase('application', "octet-stream")
            # I have a CSV file named `attachthisfile.csv` in the same directory that I'd like to attach and email
            part.set_payload(open(attachment, "rb").read())
            encoders.encode_base64(part)
            part.add_header('Content-Disposition', 'attachment', filename=file_names[i])
            msg.attach(part)
    text = msg.as_string()
    server.sendmail(FROM_ADDRESS,TO_ADDRESS, text)

 
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


def get_yaml_d(yaml_ini_file):
    """Get the Yaml Dictionary"""
    with open(yaml_ini_file) as yaml_f:
        d = yaml.load(yaml_f)
    return d


if __name__ == '__main__':
    main()
    
