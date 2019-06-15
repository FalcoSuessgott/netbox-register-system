#!/usr/bin/python
#
# Creates a virtual machine its interfaces and its ip addresses on netbox
#
# Autor:     	tom-morelly@gmx.de
# Date:      	16.04.2019
#
#

import argparse
import getpass
import math
import os
import socket
import subprocess
import sys

import psutil
import pynetbox
from terminaltables import AsciiTable

HOST = ""
TOKEN = ""


def parseArgs():
	""" Argument Parser """
	parser = argparse.ArgumentParser()
	parser.add_argument("-r", "--register", dest="register", action="store_true",
	                    help="Registers the system with at netbox.")
	parser.add_argument("-c", "--compare", dest="compare", action="store_true",
	                    help="Compares the system parameter with its registration on netbox")
	parser.add_argument("-d", "--delete", dest="delete", action="store_true",
	                    help="Deletes the system from netbox.")
	parser.add_argument("-u", "--update", dest="update", action="store_true",
	                    help="Updates the system parameter on netbox")
	parser.add_argument("-p", "--pull", dest="pull", action="store_true",
	                    help="Pulls changes from netbox and applies them to the system")

	if len(sys.argv) == 1:
		print "No arguments were specified.\nExiting."
		parser.print_help()
		sys.exit(1)

	parser = parser.parse_args()

	if len(sys.argv) >= 3:
		print "Canot specify more than two options. Please use -h option for more information.\nExiting."
		sys.exit(1)

	sudo()

	if parser.compare:
		print "[comparing system]"
		compareSystem()

	if parser.delete:
		print "[deleting system]"
		deleteSystem()
		sys.exit(0)

	if parser.register:
		print "[register system]"
		registerSystem()

	if parser.update:
		print "[deleting system]"
		deleteSystem()
		print "\n[register system]"
		registerSystem()

	if parser.pull:
		print "[pulling information]"
		password = getpass.getpass()
		# deleteSystem()
		# registerSystem()
		getClusterServer(connectToRHEV(password))


def sudo():
	""" Forces to run the application with sudo """

	if not os.getuid() == 0:
		print "Error. must be root to execute.\nExiting."
		sys.exit(1)


def auth():
	""" Authenticates to Netbox Node. """

	try:
		global nb
		nb = pynetbox.api(url="http://" + HOST, token=TOKEN)
	except Exception as e:
		print "Error while authentication.\nExiting.\n"
		print str(e)
		sys.exit(2)


def compareSystem():
	""" pulls data from netbox and prints out differents. """

	global status
	status = True
	tableData = [["Parameter", "System", "Netbox", "Match"]]
	table = AsciiTable(tableData)
	auth()
	VM = nb.virtualization.virtual_machines.get(getVirtualMachineID().id)

	tableData += compareCPU(VM)
	tableData += compareDisk(VM)
	tableData += compareMemory(VM)
	tableData += compareNetwork(VM)

	sys.stderr.write("\n" + table.table + "\n")

	if "False" in str(tableData):
		sys.stderr.write("A difference between Netbox and this System has been detected.")
		sys.stderr.write("\nRun netbox --update for updating to system onto netbox")
		sys.exit(2)
	else:
		print "No Differences occured.\nExiting."
		sys.exit(0)


def getVirtualMachineID():
	""" returns the Id of a virtual machine """

	try:
		VM = nb.virtualization.virtual_machines.get(name=socket.gethostname())
		if VM is None:
			raise Exception()
		return VM
	except Exception as e:
		print "%s does not exist. Exiting." % socket.gethostname()
		print e
		sys.exit(1)


def getInterfaceDetails(interfaceName):
	""" Returns MacAddress and IP of specified Interface """

	nics = psutil.net_if_addrs()
	interfaceDict = dict()

	for k, v in nics.items():
		try:
			if k == interfaceName:
				interfaceDict = {
					"interfaceIP": v[0].address,
					"interfaceMAC": v[2].address
				}
		except IndexError as e:
			interfaceDict = {
				"interfaceIP": None,
				"interfaceMAC": v[0].address
			}
	return interfaceDict


def compareCPU(VM):
	""" Compares system CPU with netbox CPU."""

	netboxCPU = VM.vcpus
	systemCPU = psutil.cpu_count()

	if netboxCPU == systemCPU:
		tableData = [["vCPUs", str(systemCPU), str(netboxCPU), "True"]]
	else:
		tableData = [["vCPUs", systemCPU, netboxCPU, "False"]]

	return tableData


def compareDisk(VM):
	""" Compares system disk with netbox disk"""

	disk = psutil.disk_usage('/')

	netboxDisk = VM.disk
	systemDisk = roundUp(disk.total / 2 ** 30, -1)

	if netboxDisk == systemDisk:
		tableData = [["Disk", str(systemDisk), str(netboxDisk), "True"]]
	else:
		tableData = [["Disk", systemDisk, netboxDisk, "False"]]

	return tableData


def compareMemory(VM):
	""" Compares system memory with netbox memory"""

	memory = psutil.virtual_memory()

	netboxMemory = VM.memory
	memory = psutil.virtual_memory()
	systemMemory = roundUp(memory.total / 2 ** 30, -1) * 1024

	if netboxMemory == systemMemory:
		tableData = [["Memory", str(systemMemory), str(netboxMemory), "True"]]
	else:
		tableData = [["Memory", systemMemory, netboxMemory, "False"]]

	return tableData


def compareNetwork(VM):
	""" Compares system IP, DNS and MAC with netbox IP, DNS and MAC addresses"""

	netboxInterfaces = nb.virtualization.interfaces.filter(virtual_machine_id=getVirtualMachineID().id)
	nics = psutil.net_if_addrs()
	tableData = ""

	for k, v in nics.items():
		systemDetails = getInterfaceDetails(k)

		if systemDetails['interfaceIP'] is None:
			continue

		# IP
		result = False
		if k != "lo" and "eth" in k:
			for interface in netboxInterfaces:
				if interface.name == k:
					IP = nb.ipam.ip_addresses.get(interface_id=interface.id)
					netboxIP = str(IP).split('/')[0]

			if netboxIP == systemDetails['interfaceIP']:
				result = True

			tableData = [["IP (" + k + ")", str(systemDetails['interfaceIP']), str(netboxIP), result]]

			# DNS
			result = False
			netboxDNS = ""
			for interface in netboxInterfaces:
				if interface.name == k:
					ipAddress = nb.ipam.ip_addresses.get(interface_id=interface.id)
					netboxDNS = ipAddress.description

			systemDNS = socket.gethostbyaddr(systemDetails['interfaceIP'])

			if systemDNS[0] == netboxDNS:
				result = "True"

			tableData += [["DNS (" + k + ")", str(systemDNS[0]), str(netboxDNS), result]]

			# MAC
			result = False
			netboxMacAddress = ""
			for interface in netboxInterfaces:
				if interface.name == k:
					netboxMacAddress = interface.mac_address

				if systemDetails['interfaceMAC'].upper() == netboxMacAddress:
					result = True

				tableData += [["MAC (" + k + ")", systemDetails['interfaceMAC'].upper(), netboxMacAddress, result]]

	return tableData


def deleteSystem():
	""" Deletes a system from netbox """

	auth()
	VM = getVirtualMachineID()
	VM.delete()
	print "Deleted \"%s\" from netbox." % VM.name


def registerSystem():
	""" registering a virtual machine """

	auth()

	if nb.virtualization.virtual_machines.get(name=socket.gethostname()) is not None:
		print "\"%s\" does already exist.\nExiting." % socket.gethostname()
		sys.exit(1)

	# create VM
	VM = createVM()

	# Create Interfaces
	nics = psutil.net_if_addrs()
	for k, v in nics.items():
		if k != "lo" and "eth" in k:
			interfaceDetails = getInterfaceDetails(k)

			if interfaceDetails['interfaceIP'] == None:
				pass
			else:
				createNIC = createInterface(VM, k, interfaceDetails['interfaceMAC'])
				createIP = createIPAddress(createNIC, interfaceDetails['interfaceIP'])
				if "172.28.1" in interfaceDetails['interfaceIP'] or "172.27.1" in interfaceDetails[
					'interfaceIP'] or "172.26.1" in interfaceDetails['interfaceIP'] or "172.25.1" in interfaceDetails[
					'interfaceIP'] or "172.24.1" in interfaceDetails['interfaceIP']:
					setPrimaryIP(VM, createIP)

	print "Successfully registiered \"%s\"." % socket.gethostname()
	sys.exit(0)


def createVM():
	""" Creates a virtual machine entity """

	try:
		hostname = socket.gethostname()
		vcpus = psutil.cpu_count()
		disk = psutil.disk_usage('/')
		memory = psutil.virtual_memory()
		totalDisk = roundUp(disk.total / 2 ** 30, -1)
		totalMemory = roundUp(memory.total / 2 ** 30, -1) * 1024

		virtualMachine = dict(
			name=str(hostname),
			role=8,
			cluster=1,
			platform=5,
			vcpus=vcpus,
			memory=int(totalMemory),
			disk=int(totalDisk),
		)

		VM = nb.virtualization.virtual_machines.create(virtualMachine)
		print "Created \"%s\"." % (hostname)
		return VM
	except Exception as e:
		print "Error while creating virtual machine \"%s\".\n" % (hostname)
		print str(e)
		sys.exit(0)


def getClusterServer(connection):
	""" returns the FQDN of the corresponding Cluster """

	clusterID = ""
	cls_service = connection.system_service().clusters_service()
	cls = cls_service.list()
	for cl in cls:
		print("%s (%s)" % (cl.name, cl.id))
		clusterID = cl.id

	connection.close()


def createInterface(virtualMachine, name, mac):
	""" Creates Interfaces for the virtual machine """

	try:
		interface = dict(
			name=str(name),
			virtual_machine=virtualMachine.id,
			mtu=1500,
			mac_address=str(mac),
			enabled=True
		)
		Int = nb.virtualization.interfaces.create(interface)

		print "Created interface \"%s\"." % str(name)
		return Int
	except Exception as e:
		print "Error while creating interface \"%s\".\n" % str(name)
		print str(e)


def createIPAddress(interface, address):
	""" Creates an IP Address """

	try:
		description = socket.gethostbyaddr(address)
		ipAddress = dict(
			address=str(address) + "/32",
			status=1,
			interface=interface.id,
			description=description[0])
		IP = nb.ipam.ip_addresses.create(ipAddress)
		print "Created IP address \"%s\" for NIC \"%s\"." % (str(address), str(interface.name))
		return IP
	except Exception as e:
		print "Error while creating IP address \"%s\" for NIC \"%s\"." % (str(ipAddress), str(interface.name))
		print str(e)


def setPrimaryIP(virtualMachine, ipAddress):
	""" sets the mgmt address as the primary IP """
	try:
		primary = dict(
			name=(str(virtualMachine.name)),
			cluster=4,
			primary_ip4=ipAddress.id
		)
		virtualMachine.update(primary)
	except Exception as e:
		print "Error while creating primary IP address for virtual machine \"%s\".\n" % (virtualMachine.name)
		print str(e)


def roundUp(value, decimals=0):
	""" Rounds Up an Value to the next tenth"""

	multiplier = 10 ** decimals
	return math.ceil(value * multiplier) / multiplier


if __name__ == '__main__':
	parseArgs()
