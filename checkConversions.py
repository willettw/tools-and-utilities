#!/bin/python3
import os, argparse
import sys, subprocess
from pathlib import Path

sys.path.insert(0, '/usr/lib/custom_python_modules')
sys.path.insert(1, str(Path(__file__).parent / 'custom_python_modules'))
import myfuncs, mydicts, myemail

def parse_command_line():
    # Parse command-line arguments using argparse.
    parser = argparse.ArgumentParser(description='Get conversions status.')

    # Add more parameters as needed
    parser.add_argument('-e', '--envs', dest='environments', nargs='+', help='List of environment names', default='all', required=False)
    parser.add_argument('--printit', action='store_true', help='Print results', required=False)
    parser.add_argument('--mailit', action='store_true', help='Mail results', required=False)
    parser.add_argument('--verbose', action='store_true', help='Enable verbose mode', required=False)

    try :
        args = parser.parse_args()
    except argparse.ArgumentError as e :
        print(f"Error: {e}")
        sys.exit()
    except TypeError :
        print("Error: The switch requires value(s). Example: -e poc or --environments tst prd")
        sys.exit()
    except Exception as e :
        print(f"Error in command line. Exception : {e}")
        sys.exit()
        
    return args


def get_conversion_status(env):
   
    # Build command to execute    
    command='ssh epicadm@epicpoc' + ' checkConversions.ksh ' + env
    command='ssh epicadm@' + mydicts.env_servers_dict[env] + " /usr/bin/irissession " + env + " -U" + env + " convStatus^ZIFHUtils"
    # Run the command
    try :
        #with open(output_txt, 'a') as output_file:
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell = True)
        return result.stdout.decode('utf8')
    except Exception as ex:
        print(f"Error executing command: {ex}")

def get_daemon_status(env):
    command = "ssh epicadm@" + mydicts.env_servers_dict[env] + " /usr/bin/irissession " + env + " -U" + env + " convDaemonStatus^ZIFHUtils"
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell = True)
    print(result.stdout.decode('utf8'))
    


if __name__ == "__main__":

    # Command line argument processing
    parsed_args = parse_command_line()
    verbose = parsed_args.verbose
    environments = parsed_args.environments
    mailit = parsed_args.mailit
    printit = parsed_args.printit
    
    # Debugging 
    if verbose : print(f"Verbose : {verbose}")
    if verbose : print(f"Print results : {printit}")
    if verbose : print(f"Mail results : {mailit}")
    if verbose : print(environments)

    if environments=='all':
        environments = []
        for env in mydicts.env_servers_dict.keys():
            if (env not in 'rpt,dr,sro'):
                environments.append(env)

    report_body=f'Status of conversions in {environments} \n\n'
    for env in environments:
        if verbose : print('Env : ' + env)
        report_body += str(get_conversion_status(env))
    if mailit:        
        myemail.send_email(to=['wwillett@institute.org'], subject='Epic Conversions Status', body=report_body, email_type='html')
    if printit:
        print(report_body)
    
    