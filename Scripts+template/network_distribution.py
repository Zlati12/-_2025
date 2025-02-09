from jnpr.junos import Device
from jnpr.junos.exception import ConnectError
import traceback
import ipaddress
from collections import deque
from junos import Junos_Context
import jcs
import traceback
import re

class RadixTreeNode:
    def __init__(self, subnet):
        # Initialize a node in the radix tree with a given subnet
        self.subnet = subnet
        self.children = []

    def add_child(self, child):
        # Add a child node to the current node
        self.children.append(child)


def build_radix_tree(network, max_prefix_length):
    # Create the root of the radix tree with the provided network
    root = RadixTreeNode(network)
    queue = deque([root])

    # Perform a level-order traversal to build the radix tree
    while queue:
        node = queue.popleft()
        # Split the current subnet into smaller subnets if prefix length allows
        if node.subnet.prefixlen < max_prefix_length:
            subnets = list(node.subnet.subnets(
                new_prefix=node.subnet.prefixlen + 1))
            for subnet in subnets:
                # Create a child node for each subnet and add it to the current node
                child_node = RadixTreeNode(subnet)
                node.add_child(child_node)
                queue.append(child_node)

    return root


def assign_subnets(radix_tree, n_devices, max_prefix_length):
    # Initialize the devices dictionary to store assigned subnets for each device
    devices = {i: [] for i in range(n_devices)}

    # Total number of IPs in the network
    remaining_ips = radix_tree.subnet.num_addresses
    device_index = 0  # Index to keep track of which device to assign next

    # Assign subnets to devices while there are unassigned IPs and subnets left in the tree
    while remaining_ips > 0 and radix_tree.children:
        # Calculate the number of IPs that should be assigned to each device
        ips_per_device = remaining_ips // n_devices
        next_level_nodes = []  # List to store the nodes for the next level

        # Traverse the current level of the radix tree to assign subnets
        for child in radix_tree.children:
            if child.subnet.num_addresses <= ips_per_device:
                # Assign the subnet to the current device if it fits within the IP limit
                devices[device_index].append(child.subnet)
                remaining_ips -= child.subnet.num_addresses
                if device_index == n_devices-1:
                    ips_per_device = remaining_ips // n_devices
                # Move to the next device in a round-robin fashion
                device_index = (device_index + 1) % n_devices
            elif int(child.subnet.prefixlen) < int(max_prefix_length):
                # If the subnet is too large, add it to the next level for further splitting
                next_level_nodes.append(child)
            else:
                devices[device_index].append(child.subnet)
                device_index = (device_index + 1) % n_devices

        # Update the children of the radix tree to point to the next level
        radix_tree.children = [
            child for node in next_level_nodes for child in node.children]

    return devices


def get_bgp_neighbors():

    # Get the device handle using the built-in context
    dev = Device()

    try:
        jcs.output("Attempting to connect to device...")

        # Open the connection
        dev.open()

        jcs.output("Connection established successfully!")

        # Get BGP neighbor information using native RPC
        jcs.output("Fetching BGP neighbor information...")
        bgp_info = dev.rpc.get_bgp_neighbor_information()

        # Count total neighbors
        total_neighbors = len(bgp_info.findall('.//bgp-peer'))

        # Close the connection
        dev.close()

        return total_neighbors

    except ConnectError as e:
        jcs.output("\nError: Unable to connect to the device.")
        jcs.output("Details: ", e)
        jcs.output("Traceback: ", traceback.format_exc())
    except Exception as e:
        # Log the error using syslog or standard output
        jcs.output("\nUnexpected error occurred:")
        jcs.output(f"Error: {e}")
        jcs.output("Traceback: ", traceback.format_exc())
        if dev:
            dev.close()
        return 0


# %%% Main Program
if __name__ == '__main__':
    # Get the total number of BGP neighbors (replaces n_devices)
    n_devices = get_bgp_neighbors()

    if n_devices == 0:
        jcs.output("No BGP neighbors found. Exiting...")
    else:
        jcs.output(f"Total BGP neighbors: {n_devices}")

        devices = {i: [] for i in range(n_devices)}
        networks = [{'network': "10.250.0.0/24", 'max_prefix_length': 28}]

        # Build the radix tree for the given network
        for net in networks:
            radix_tree = build_radix_tree(ipaddress.ip_network(
                net['network'], strict=False), net['max_prefix_length'])

            # Assign subnets to devices using the radix tree
            devices = assign_subnets(radix_tree, n_devices,
                                    net['max_prefix_length'])

        total_ips = 0
        # Print the results for each device
        for device, assigned_subnets in devices.items():
            total_assigned_ips = sum(
                subnet.num_addresses for subnet in assigned_subnets)
            total_ips += total_assigned_ips
            jcs.output(
                f"Device {device}: Total IPs: {total_assigned_ips} ; Subnets {', '.join(map(str, assigned_subnets))}")
        jcs.output(f"Total number of IPs: {total_ips}")
