from Tooling import *
import time
import subprocess
import argparse
import os
import yaml
import json
from tabulate import tabulate
import re

#yaml content to variables
with open("xpath_env.yaml") as settings:
  settings_dict= yaml.load(settings, Loader=yaml.FullLoader)
  globals().update(settings_dict)
# From the above we get:
            # # source directory location [ All in absolute paths]
            # yang_dir: "/root/native/git/api-publish/tools/jdev/dcb" # Juniper directory that contains all openconfig files - from release branch or dcb 
            # deviation_source_file: "/root/native/git/api-publish/tools/jdev/jnx-openconfig-dev.yang" # file that contains juniper deviations
            # plugin_dir: "./xpath_plugin_dir"
            # platform_annotation: "/root/openconfig-schema.xml"

            # #Device info
            # dut: "rx" # Device name or ip
            # port: 50051 # gnmi port
            # username: "root"
            # password: "Embe1mpls"

            # #test info

            # test_release: "21.3"
            # test_platform: "VMX"

# Create the argument parser
parser = argparse.ArgumentParser(description='Process .yang files.')
parser.add_argument('-f', '--input_yang_model', required=True, help='The name of the .yang file')
group = parser.add_mutually_exclusive_group(required=True)
group.add_argument("-g", "--generate_ds", action="store_true", help="Set this to generate dataset file")
group.add_argument("-d", "--data_header_file", help="header file name to update dataset")

group.add_argument("-e", "--execute_test", action="store_true", help="Set this to execute testcases")
parser.add_argument('-s', '--data_set', help='The name of the filled dataset file')
parser.add_argument('-r', '--rpc_mapping_file', help='The name of the rpc mapping file')
parser.add_argument("-l", "--debug_level", choices= ['0','1','2'], default= '0', help="Run in debug mode")
parser.add_argument("-a", "--all_paths", action="store_true", help="Set this to execute state paths as well")

args = parser.parse_args()
filled_dataset_file = args.data_set
# Logging
if args.execute_test or args.data_header_file:
    if not args.data_set:
        print("dataset file is mandatory to execute tests. Use --help to know the option")
        exit()
if args.all_paths:
    all_paths = args.all_paths
    if args.data_header_file or args.execute_test:
        if not args.rpc_mapping_file:
            print("rpc mapping file is mandatory for pre filling dataset if all path is set . Use --help to know the option")
            exit()
        else:
            rpc_mapping_file = args.rpc_mapping_file             

    
debug = int(args.debug_level)
input_yang_model = args.input_yang_model


# Extract the directory if the input yang model is provided with a full path
if os.path.dirname(input_yang_model):
    yang_dir = os.path.dirname(input_yang_model)
file_name_prefix = os.path.splitext(os.path.basename(input_yang_model))[0]

# Filename creation
time_stamp = time.strftime("%Y%m%d-%H%M%S")
dataset_filename = "{}-dataset-{}.yaml".format(file_name_prefix,time_stamp)
tc_filename = "{}-tc-{}.yaml".format(file_name_prefix,time_stamp)
tc_result_filename = "{}-tc_result-{}.json".format(file_name_prefix,time_stamp)
tc_result_table_filename = "{}-tc_summary-{}.txt".format(file_name_prefix,time_stamp)
xpath_full_list_filename = "{}-xpath_list.txt".format(file_name_prefix)
xpath_rpc_mapping_filename = "{}-rpc_mapping.yaml".format(file_name_prefix)
xpath_data_header_filename = "{}-data_header.txt".format(file_name_prefix)




# log_file = "{}-{}.log".format(file_name_prefix, time.strftime("%Y%m%d-%H%M%S"))
log_file = "{}.log".format(file_name_prefix)
log_file_handle = open(log_file, 'w+')
my_log= MyLog(log_file_handle,debug)



# Extracting Open config package
def extract_oc_pkg():
    tmp_pkg_dir = "/tmp/tmp_pkg"
    execute_shell_cmd(f"mkdir {tmp_pkg_dir}")
    cmd = "tar -xvf {} -C {}/".format(openconfig_pkg, tmp_pkg_dir)
    execute_shell_cmd(cmd)
    yang_dir = f"{tmp_pkg_dir}/openconfig/yang"
    deviation_source_file = f"{tmp_pkg_dir}/openconfig/deviation/jnx-openconfig-dev.yang"
    return(yang_dir,deviation_source_file)




def generate_custom_models():
    import oc_config_validate
    import pyangbind

    models_path = os.path.dirname(oc_config_validate.__file__) + "/models"
    pyangbind_plugin = "{}/plugin".format(os.path.dirname(pyangbind.__file__))
    py_model = file_name_prefix.replace("openconfig","joc").replace("-","_") + ".py"
    cmd = f"grep -rl 'import {file_name_prefix} ' {yang_dir} | tr '\n' ' ' | xargs pyang --plugindir {pyangbind_plugin} -f pybind --ignore-errors --path {yang_dir} --output {py_model} {yang_dir}/{input_yang_model} "
    my_log.log(f"Executing: {cmd}")
    execute_shell_cmd(cmd)
    execute_shell_cmd(f"mv {py_model} {models_path}")




    # pyang --plugindir /root/nv/lib/python3.9/site-packages/pyangbind/plugin -f pybind --path openconfig/:junos/ --output joc_system.py openconfig/yang/openconfig-system.yang openconfig/yang/openconfig-system-grpc.yang --ignore-errors
    

def search_files(file_list):
    not_found = []

    for file_name in file_list:
        if not os.path.exists(file_name):
            not_found.append(file_name)

    if not_found:
        my_log.log("Not all required Files are found:")
        for file_name in not_found:
            my_log(file_name)
        return False
    else:
        my_log.log("All required yang files found. Proceeding!")
        return True

def execute_tc():
    cmd = f'python -m oc_config_validate -tests {tc_filename} -results {tc_result_filename} --target {dut}:{port} --username {username} --password {password} -f json --no_tls --log_gnmi'
    print(cmd)
    subprocess.call(cmd,shell=True)
def generate_tc(file_name_prefix, dataset_filename,tc_filename):
    # Header for output YAML


    # Read input YAML file
    with open(dataset_filename, 'r') as f:
        input_yaml = f.read()
    
    model = "joc_" + file_name_prefix.split("openconfig-")[1] + "." + file_name_prefix.replace("-","_")
    tc_count = 0
    xpath_test_list = []
    xpath_full_list = get_lines(xpath_full_list_filename)

    # Parse input YAML file and generate test cases
    output_yaml = ''
    
    dataset_dict = yaml.safe_load(input_yaml)
    data_input_xpath_count = len(dataset_dict.keys())
    for key, values in dataset_dict.items():
        parent_key = str(key.rsplit("/config",1)[0])
        parent_key_lookup = re.sub(r'\[.*?\]', '', parent_key)
        key_lookup = re.sub(r'\[.*?\]', '', key)
        subscribe_key = key.replace("/config/","/state/")
        subscribe_key_lookup = re.sub(r'\[.*?\]', '', subscribe_key)
        subscribe_state_key = parent_key + "/state"
        subscribe_state_key_lookup = re.sub(r'\[.*?\]', '', subscribe_state_key)
        additional_get_key = parent_key + "/config"
        additional_get_key_lookup = re.sub(r'\[.*?\]', '', additional_get_key)
        
        
        print(subscribe_key,subscribe_key_lookup,subscribe_state_key,subscribe_state_key_lookup, additional_get_key,additional_get_key_lookup,parent_key,parent_key_lookup)

        
        for value in values:
            if value is not None:
                tc_count += 1
                test_case = f"""
- !TestCase
  name: "set and get {key} to {value}"
  class_name: setget.SetGetJsonCheckCompare
  args:
    xpath: "{key.rsplit('/',1)[0]}"
    model: {model}
    json_value: {{
    "{key.split('/')[-1]}": {value}
    }}

"""
                if subscribe_key_lookup in xpath_full_list and subscribe_key_lookup not in xpath_test_list:
                    tc_count += 1
                    test_case += f"""
- !TestCase
  name: "Subscribe {subscribe_key} to check for {value}"
  class_name: telemetry_once.CountUpdatesCheckType
  args:
    xpaths: ["{subscribe_key}"]
    model: {model}
    values_type: "{value}"
    updates_count: 1

"""
                if subscribe_state_key_lookup in xpath_full_list and subscribe_state_key_lookup not in xpath_test_list:
                    tc_count += 1
                    test_case += f"""
- !TestCase
  name: "Subscribe {subscribe_state_key} to test response schema"
  class_name: telemetry_once.CheckLeafs
  args:
    xpaths: ["{subscribe_state_key}"]
    model: {model}

"""
                if additional_get_key_lookup in xpath_full_list and additional_get_key_lookup not in xpath_test_list:
                    tc_count += 1
                    test_case += f"""
- !TestCase
  name: "Get config hierarchy {additional_get_key} to test schema and value {value}"
  class_name: get.GetJsonCheck
  args:
    xpath: "{additional_get_key}"
    model: {model}

"""
                if parent_key_lookup in xpath_full_list and parent_key_lookup not in xpath_test_list:
                    tc_count += 2
                    test_case += f"""
- !TestCase
  name: "Get config hierarchy {parent_key} to test schema and value {value}"
  class_name: get.GetJsonCheck
  args:
    xpath: "{parent_key}"
    model: {model}

- !TestCase
  name: "Subscribe {parent_key} to test response schema"
  class_name: telemetry_once.CheckLeafs
  args:
    xpaths: ["{parent_key}"]
    model: {model}

"""

            key_list = [key_lookup,subscribe_key_lookup,subscribe_state_key_lookup,additional_get_key_lookup,parent_key_lookup]
            for test_key in key_list:
                if test_key not in xpath_test_list:
                    xpath_test_list.append(test_key)
            output_yaml += test_case
    






    if args.all_paths is True:
        with open(rpc_mapping_file) as fh:
            rpc_yaml =fh.read()
        state_path_dict = yaml.safe_load(rpc_yaml)
        state_cmd_list = state_path_dict.keys()
        for state_cmd in state_cmd_list:
            tc_count += 1
            test_case += f"""
- !TestCase
  name: "Subscribe {state_cmd} to test response schema"
  class_name: telemetry_once.CheckLeafs
  args:
    xpaths: ["{state_cmd}"]
    model: {model}

"""
            test_key = re.sub(r'\[.*?\]', '', state_cmd)
            xpath_test_list.append(test_key)
            output_yaml += test_case


    coverage = round(((len(xpath_test_list)/len(xpath_full_list))*100), 2)
    config_paths_count = int(get_list_from_output(f"grep '/config/' {xpath_full_list_filename} | wc -l")[0])
    summary = f"Total xpaths - {len(xpath_full_list)} , Set config paths - {config_paths_count}, Data Input xpaths - {data_input_xpath_count}, Tested xpaths - {len(xpath_test_list)}, Test Coverage - {coverage}%"
    my_log.log(summary)
    header = """!TestContext

description: Testing {0} model with - Total TCs:{1}. Test Summary - \"{2}\"

labels:
- {0}
""".format(file_name_prefix,tc_count,summary)

    # Write output YAML to file
    with open(tc_filename, 'w+') as f:
        f.write(f"{header}\ntests:\n{output_yaml}")

    # Print expected output YAML
    print(f"{header}\ntests:\n{output_yaml}")
    
    return summary

# Function to recursively process the XML elements
def process_element(element, path):
    # Remove the namespace prefix from the tag
    tag = element.tag.split('}')[1]    
    # Get the full path
    if path:
        full_path = f"{path}/{tag}"
    else:
        full_path = f"{tag}"    
    # Get the value
    value = element.text.strip() if element.text else ''    
    # Add the key-value pair to the dictionary
    platform_matrix[full_path] = value    
    # Process child elements
    for child in element:
        process_element(child, full_path)






# Parsing result
def parse_result(tc_result_filename,summary='Total xpaths - 445 , Set config paths - 84, Data Input xpaths - 3, Tested xpaths - 9, Test Coverage - 2.02%'):
    summary = "Test Summary<\/td><td>" + summary.replace(",","<\/td><td>")
    
    html_report_filename = "{}-{}.html".format(file_name_prefix,time_stamp)
    # Load the JSON data
    with open(tc_result_filename, 'r') as f:
        data = json.load(f)
    table = []
    s_no=0
    

    
    for result in data['results']:
        s_no += 1
        test_name = result['test_name']
        xpath = re.findall("(/.*) to ",test_name)[0]
        xpath = re.sub("\[.*\]","",xpath)
        
        
        success = result['success']
        duration_sec = result['duration_sec']
        status = 'PASS' if success else 'FAIL'
        grpc_message = ""
        #grpc_message = result['results'][-1]['log']['grpc_message']
        log_string = result['results'][-1]['log']
        set_status = "PASS"
        get_status = "PASS"
        sub_status = "PASS"
        
        if xpath in deviation_list:
            deviation = "Yes"
        else:
            deviation = "No"



        
        if test_name.startswith("Subscribe"):
            set_status = "NA"
            get_status = "NA"
            if status == "FAIL":
                sub_status = "FAIL"
        elif test_name.startswith("Get config"):
            set_status = "NA"            
            sub_status = "NA"
            if status == "FAIL":
                get_status = "FAIL"
        else:
            sub_status = "NA"
            if status == "FAIL":
                if "SET FAILED" in log_string:
                    set_status = "FAIL"
                    get_status = "NA"
                elif "GET FAILED" in log_string:
                    get_status = "FAIL"
                else:
                    set_status = get_status = "FAIL"

            
                # Extract status and details using regular expressions
                status_match = re.search(r"status = StatusCode.(\w+)", log_string)
                details_match = re.search(r"details = \"([\s\S]*?)\"", log_string)
                assertion_match = re.findall(r"AssertionError:(.+)\n", log_string)[0]

                # Check if matches were found and extract the values
                #status = status_match.group(1) if status_match else ""
                details = details_match.group(1).replace("\n", "").strip() if details_match else ""
                grpc_message = details if details != "" else assertion_match
            
        if deviation == "Yes":
            status = status + "(D)"
        if xpath in product_map.keys():
            if test_platform in product_map[xpath]:
                platform = "S"
            else:
                platform = "NS"
                status = status + f"(P-{platform})"
                grpc_message += str(product_map[xpath])
        else:
            platform = "NA"
            status = status + f"(P-{platform})"     

        # print(grpc_message)
        table.append([s_no, xpath, test_name, set_status, get_status, sub_status, deviation, platform, status, grpc_message])

    # Display the summary table
    print(tabulate(table, headers=['S.No', 'Xpath', 'Testcase', 'Set', 'Get', 'Subscribe', 'Deviation', f'Platform ({test_platform})', 'Result', 'Message']))

    with open("content.html", "w+") as fh:
        fh.write(tabulate(table, headers=['S.No', 'Xpath', 'Testcase', 'Set', 'Get', 'Subscribe', 'Deviation', f'Platform ({test_platform})', 'Result', 'Message'],tablefmt='html'))

    execute_shell_cmd("sed -i '1d;$d' {}".format("content.html"))
    execute_shell_cmd("sed '/xpath_result/ r content.html' template.html > {}".format(html_report_filename))
    cmd = "sed -i 's/xpath_summary/{}/' {}".format(summary, html_report_filename)
    print(cmd)
    execute_shell_cmd(cmd)

    execute_shell_cmd("cp {} /var/www/html/".format(html_report_filename))

#

def generate_dataset():
    dependent_file_list_cmd = "grep -l 'import {} ' {}/*.yang".format(file_name_prefix,yang_dir)
    yang_file_list = get_list_from_output(dependent_file_list_cmd)
    if not search_files(yang_file_list):
        exit()
    else:        
        yang_file_list_str = " ".join(yang_file_list)
        pyang_cmd = "pyang -f xpath --plugindir {} --path {} {}/{} {} -o {}| grep '\-\-\-' > {}".format(plugin_dir, yang_dir, yang_dir,input_yang_model,yang_file_list_str,xpath_full_list_filename, dataset_filename )
        my_log.log("Executing: {}".format(pyang_cmd))
        execute_shell_cmd(pyang_cmd)
        xpath_full_list = get_lines(xpath_full_list_filename)
        xpath_state_only_list =[]
        for xpath in xpath_full_list:
            if "state" in xpath:
                c_xpath = xpath.replace("state","config")
                if c_xpath not in xpath_full_list:
                    xpath_state_only_list.append(xpath)
        rpc_mapping_dict = {xpath:"" for xpath in xpath_state_only_list}
        ONEMILLION = 2


        with open(xpath_rpc_mapping_filename, "w+") as fh:
            for xpath in xpath_state_only_list:
                fh.write(f"{xpath}: ''\n")           
            #yaml.dump(rpc_mapping_dict,fh,width=1000, default_flow_style=False)
            
        # print(xpath_state_only_list)
        #cat openconfig-system-xpath_list.txt | grep = | grep -o '.*\]' | sort | uniq
        cmd = "cat " + xpath_full_list_filename + " | grep = | grep -o '.*\]' | sort | uniq"
        data_headers_list = get_list_from_output(cmd)
        with open(xpath_data_header_filename, "w+") as fh:
            for line in data_headers_list:
                fh.write(f"{line}\n")
        

        # unique_xpath_in_dataset = set([s.split('/config/', 1)[-1] for s in get_lines(dataset_filename)]) # has comments
        unique_xpath_in_dataset = set([s.split('/config/', 1)[-1].split('---')[0].strip() for s in get_lines(dataset_filename)]) # no comments

        #append unique xpath to dataset
        with open(xpath_data_header_filename, "a") as fh:
            fh.write("\n\n#LEAFS\n\n")
            for xpath in unique_xpath_in_dataset:
                fh.write(f"{xpath}\n") 


def pre_fill_dataset(file_list):

    # Filling values for state commands from filled dataset file
    
    all_header_lines = get_lines(data_header_file)
    leaf_index = all_header_lines.index("#LEAFS")
    leaf_xpaths = all_header_lines[leaf_index+2:]
    xpath_list_to_fill = all_header_lines[:leaf_index-2]

    for xpath in xpath_list_to_fill: # TODO I haven't touched this but it doesn't seem to work since it doesn't seem to edit the dataset file. - Anshul
        search_cmd_pattern = re.sub(r"=(.*?)\]", r"=(.*?)\]", xpath)
        print(xpath)
        search_cmd_pattern = re.sub(r"\[", r"\\[", search_cmd_pattern)
        search_cmd_pattern = re.sub(r"\]", r"\\]", search_cmd_pattern)
        
        print(search_cmd_pattern)
        for file_name in file_list:
            search_xpath_cmd = "cat " + file_name + " | grep -E \"" + search_cmd_pattern + "\" | grep -o '.*: ' | grep -o '.*\]' | sort | uniq" # cat filled_openconfig-system-dataset.yaml | grep -E "/system/aaa/server-groups/server-group\[name=(.*?)\]/servers/server\[address=(.*?)\]" | grep -o '.*: ' | grep -o '.*\]' | sort | uniq==>/system/aaa/server-groups/server-group[name=<string>]/servers/server[address=<ocnet:ipdaddress>]
            search_xpath = get_list_from_output(search_xpath_cmd)[0]
            sed_command = "sed -i 's|" + search_xpath.replace("[", "\[").replace("]", "\]") + "|" + xpath.replace("[", "\[").replace("]", "\]") + "|g' " + file_name
            print(sed_command)
            execute_shell_cmd(sed_command)
          
    # Filling values for leafs from header file
    # TODO same name, different datatype is broken
    for entry in leaf_xpaths:
        line_without_comments = entry.split('#')[0].strip()
        key, value = [x.strip() for x in line_without_comments.split(':')]
        # Escape square brackets
        escaped_value = value.replace("[", "\[").replace("]", "\]")
        # Construct the sed command
        sed_command = f"sed -i 's|{key}: \[\]|{key}: {escaped_value}|g' {filled_dataset_file}"
        # Execute the command
        os.system(sed_command)

def build_common_lookup_file():
    # should build the common lookup file
    """
    How one that has some values should look - a blank version of this is what this function should build, it should build it based on the header file
    for all the yang models in the directory
    <oc-inet:ip-address>:
        default:
            valid: 
                ["192.168.1.1"]: 70
                "10.0.0.2": 30
            boundary:
                "0.0.0.0": 50
                "255.255.255.255": 50
            negative:
                "256.256.256.256": 60
                "abc.def.ghi.jkl": 40
        ntp-source-address:
            valid: 
                "192.168.2.1": 60
                "10.0.0.3": 40
            boundary:
                
            negative:
    
        <boolean>:
        default:
            valid:
            true: 60
            false: 40
            boundary: {} # For booleans, boundary might not make sense, hence an empty dictionary.
            negative:
            "true": 70
            123: 30


    TODO: Figure out how to implement lists - right now I can't have lists as the key in yaml. 
    - maybe convert list to a string? - This is will also work for lists of lists
    - maybe have everything be a list 
    - how would it handle lists of lists - convert any single quotes inside the list to double quotes and then just put it there with single quotes and directly put this into the 
    - header file. 

                items:
            - a
            - b
            - c
            - d
            - e
            value: 50

            ?? 

    
    
    pull this file: https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-types.html#openconfig-types-identities

    https://github.com/openconfig/public/tree/master/release/models/types - this also has patterns - can use the patterns to generate some examples

    also use it for comments for each datatype


    yang 
    """
    ... 
    

def update_common_lookup_file():
    # should update the common lookup file (probably compare two header files - if the user makes changes find the changes and then use those to update the 
    # common lookup file's frequency distribution)
    # can also add a certainty feature - like say this was use x number of times before. 
    # 
    ... 
def update_prefiller(): #inputs - header file, common dataset file? 
    # should update the prefiller, should also output the number of things that were updated and percentage of things that were updated
    # adds to the end of the comment (autofilled) or some other flag - 
        # two options a) tell user to remove flag to count that for updating the lookup doc b) store a copy of the lookup doc and then use that to update the lookup doc 
    # this function should also add all the missing things to the lookup doc
    
    #Steps
        # 1. get all the relevant bits from the leafs (add logic for the headers later)
        # 2. loop through each 
        #   - if datatype exists: 
        #      - if value exists: use the value in value 
        #      - if value doesn't exist: use the default value listed in the datatype add comment flag (AUTOFILLED)
        #  - if datatype doesn't exist:
        #    - add datatype to the lookup doc  
        #    - 
    ... 

# Set up all the openconfig files
if "openconfig_pkg" in globals():
    if openconfig_pkg is not None:
        yang_dir,deviation_source_file = extract_oc_pkg()

#generate and copy costum python models for the yang files
# generate_custom_models()

def build_product_map(xpath_prefix):
    for key, value in platform_matrix.items():
        if key.endswith("/path"):
            if value.startswith(xpath_prefix):
                new_key = key[:-4] + "product"
                if new_key in platform_matrix.keys():                
                    product_map[value] = platform_matrix[new_key].split()
    return



# Generate skeleton dataset file or execute testcase
if args.generate_ds:
    my_log.log("Generating Dataset")
    generate_dataset()
elif args.data_header_file:
    
    data_header_file = args.data_header_file
    file_list = [data_header_file]
    if args.all_paths:        
        file_list.append(rpc_mapping_file)

    pre_fill_dataset(file_list)
elif args.execute_test:
    # Building platform mapping
    import xml.etree.ElementTree as ET
    from collections import OrderedDict
    with open(platform_annotation_file, 'r') as file:
        xml_data = file.read()
    root = ET.fromstring(xml_data)
    platform_matrix = OrderedDict()
    process_element(root, '')

    product_map = OrderedDict()
    cmd = f"head -n 1 {filled_dataset_file} | awk {{'print $1'}} | cut -d / -f 2"
    xpath_prefix = "/" + str(get_list_from_output(cmd)[0])
    build_product_map(xpath_prefix)

    # Suren
    # Building deviation list
    deviation_list = get_lines("deviation_list")

    summary = generate_tc(file_name_prefix, filled_dataset_file,tc_filename)
    execute_tc()
    parse_result(tc_result_filename,summary)
    # parse_result("openconfig-system-tc_result-20230627-061754.json")




# Backup

        # cmd = f"cat {xpath_rpc_mapping_filename} | grep = | grep -o '.*\]' | sort | uniq"
        # state_cmd_list_to_fill = get_list_from_output(cmd)
        # print(state_cmd_list_to_fill)
        # for state_cmd in state_cmd_list_to_fill:
        #     state_cmd_pattern = re.sub(r"\[", r"\\[", state_cmd)
        #     state_cmd_pattern = re.sub(r"\]", r"\\]", state_cmd_pattern)
        #     state_cmd_pattern = re.sub(r"=<(.*?)>", r"=(.*?)", state_cmd_pattern)
            
        #     state_cmd_to_match = "cat " + dataset_filename + " | grep -E \"" + state_cmd_pattern + "\" | grep -o '.*: ' | grep -o '.*\]' | sort | uniq" # cat filled_openconfig-system-dataset.yaml | grep -E "/system/aaa/server-groups/server-group\[name=(.*?)\]/servers/server\[address=(.*?)\]" | grep -o '.*: ' | grep -o '.*\]' | sort | uniq==>/system/aaa/server-groups/server-group[name=test_group]/servers/server[address=5.5.5.5]
        #     print(state_cmd_to_match)
        #     matching_path_list = get_list_from_output(state_cmd_to_match)
        #     print(f"mapping:{state_cmd} => {matching_path_list}, {len(matching_path_list)}")
        #     if matching_path_list[0] != "":
        #         matching_path = matching_path_list[0]     
        #         print(matching_path)       
        #         print("suren")
        #         #creating sed command to search for all the state commands that can be filled with values from above matching command in the filled dataset
        #         sed_command = "sed -i 's|" + state_cmd.replace("[", "\[").replace("]", "\]") + "|" + matching_path.replace("[", "\[").replace("]", "\]") + "|g' " + xpath_rpc_mapping_filename
        #         print(sed_command)
        #         execute_shell_cmd(sed_command)       

        #     else:
        #         print(f"Manually fill for {state_cmd}")
        # with open(xpath_rpc_mapping_filename) as fh:
        #     rpc_yaml =fh.read()
        # state_path_dict = yaml.safe_load(rpc_yaml)
        # state_cmd_list = state_path_dict.keys()
        # print(state_cmd_list)
        # exit()
