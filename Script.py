from jinja2 import Template
from jnpr.junos import Device
from jnpr.junos.utils.config import Config
from jnpr.junos.exception import ConnectError, ConfigLoadError, CommitError
from network_distribution import build_radix_tree, assign_subnets, get_bgp_neighbors
import ipaddress
from junos import Junos_Context
import jcs
import traceback
import re


# Load the Jinja2 template
template_path = "/var/db/scripts/op/config_template.j2"
cleanup_config="""
wildcard delete policy-options prefix-list SRX*
wildcard delete firewall filter egress-FBF term SRX*
wildcard delete firewall filter ingress-FBF term SRX*
"""

try:
    with open(template_path, "r") as file:
        template_content = file.read()

    template = Template(template_content)

    # Get the total number of BGP neighbors (replaces n_devices)
    n_devices = get_bgp_neighbors()

    if n_devices == 0:
        jcs.output("No BGP neighbors found. Exiting...")
    else:
        jcs.output(f"Total BGP neighbors: {n_devices}")

        # Start IP address and IP internal
        start_ip = ipaddress.IPv4Address("10.1.1.2")
        devices_config = []

        # Generate configuration for each device

        # Simulate assigning subnets for devices
        devices = {i: [] for i in range(n_devices)}
        networks = [{'network': "10.250.0.0/24", 'max_prefix_length': 28},
                    {'network': "10.255.0.0/24", 'max_prefix_length': 28},
                    {'network': "10.254.0.0/24", 'max_prefix_length': 28}]

        # Build the radix tree for the given network
        for net in networks:
            radix_tree = build_radix_tree(ipaddress.ip_network(
                net['network'], strict=False), net['max_prefix_length'])

            # Assign subnets to devices using the radix tree
            new_devices = assign_subnets(radix_tree, n_devices,
                                         net['max_prefix_length'])
            # Merge results into the main devices dictionary
            for device, subnets in new_devices.items():
                devices[device].extend(subnets)

        # Print the dictionary of devices and their assigned subnets
        jcs.output("Assigned subnets to devices:")
        for device, assigned_subnets in devices.items():
            total_assigned_ips = sum(
                subnet.num_addresses for subnet in assigned_subnets)
            jcs.output(f"Device {device}: Total IPs: {total_assigned_ips} ; Subnets {', '.join(map(str, assigned_subnets))}")
            ip_address = str(start_ip + device)
            ip_internal = str(start_ip + device - 256)  # Subtract 256 to modify third octet
            prefix_name = f"SRX-{ip_address}"

            variables = {
                "prefix_name": prefix_name,
                "ip_address": ip_address,
                "ip_internal": ip_internal,
                'subnets' : [x for x in assigned_subnets]
            }

            config_commands = template.render(variables)
            devices_config.append((prefix_name, config_commands))
            jcs.output(f"Generated Configuration for Device {device}:")
            jcs.output(config_commands)
# cu.load('wildcard delete policy-options prefix-list SRX*\n wildcard delete firewall filter egress-FBF term SRX*\n wildcard delete firewall filter ingress-FBF term SRX*\n',format='set',ignore_warning=True)
        # Connect to the devices and configure
        jcs.output(f"Connecting to the device at local device...")
        with Device() as dev:
            jcs.output("Connection successful!")
            dev.open()
            # Open a configuration session
            with Config(dev, mode='private') as cu:
                cu.load(cleanup_config,format='set',ignore_warning=True)
                for prefix_name, config_commands in devices_config:
                    jcs.output(f"Loading configuration for {prefix_name}...")
                    cu.load(config_commands, format='set')

                # Commit the configuration
                jcs.output("Diff of the configuration...")
                jcs.output(cu.diff())
                jcs.output("Committing the configuration...")
                cu.commit()
                jcs.output("Configuration successfully committed!")

except FileNotFoundError:
    jcs.output(f"Template file {template_path} not found.")
except ConnectError as err:
    jcs.output(f"Failed to connect to device: {err}")
except ConfigLoadError as err:
    jcs.output(f"Failed to load configuration: {err}")
except CommitError as err:
    jcs.output(f"Failed to commit configuration: {err}")
except Exception as e:
    jcs.output(f"An unexpected error occurred: {e}")
