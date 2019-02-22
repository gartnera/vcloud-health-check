import json
import socket
import time
import datetime
import ssl
from urllib.request import urlopen

from colorama import Fore, Style
from pyvcloud.vcd.client import BasicLoginCredentials
from pyvcloud.vcd.client import Client
from pyvcloud.vcd.org import Org
from pyvcloud.vcd.vdc import VDC
from pyvcloud.vcd.vapp import VApp
from pyvcloud.vcd.vm import VM
import paramiko

class IgnoreHostKeyPolicy:
    def missing_host_key(self, client, hostname, key):
        return True

socket.setdefaulttimeout(10)

# load config
with open('config.json', 'r') as f:
    config = json.load(f)

client = Client(config['url'])
client.set_highest_supported_version()
client.set_credentials(BasicLoginCredentials(config['user'], config['org'], config['password']))

print("Fetching Org...")
org = Org(client, resource=client.get_org())

print("Fetching VDC...")
vdc = VDC(client, resource=org.get_vdc(config['vdc']))

print("Fetching vApp...")
vapp_resource = vdc.get_vapp(config['vapp'])
vapp = VApp(client, resource=vapp_resource)

print("Validating VMs...")
vms = vapp.get_all_vms()

names = map(lambda vm: vm.get('name'), vms)
names = list(names)

services = config['services']
for service in services:
    name = service['vm']
    index = names.index(name)
    service['resource'] = vms[index]

def health_check_tcp(service):
    s = socket.socket()
    try:
        s.connect((service['ip'], service['port']))
        s.recv(100)
        s.close()
        return True
    except:
        s.close()
        return False

def health_check_urlopen(service, proto):
    ip = service['ip']
    port = service['port']
    url = service['url']

    try:
        res = urlopen(f'{proto}://{ip}:{port}{url}', context=ssl._create_unverified_context())
        code = res.getcode()
        if code == 200:
            return True
        else:
            return False
    except:
        return False

def health_check_ssh(service):
    ip = service['ip']
    port = service['port']
    username = service['username']

    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(IgnoreHostKeyPolicy)
        client.connect(ip, username=username, password='', port=port)
        client.close()
        return True
    except Exception as e:
        print(e)
        return False

def health_check(service):
    check = service['check']
    if check == 'tcp':
        return health_check_tcp(service)
    elif check == 'ssh':
        return health_check_ssh(service)
    elif check == 'http':
        return health_check_urlopen(service, 'http')
    elif check == 'https':
        return health_check_urlopen(service, 'https')
    else:
        raise "Invalid check type: " + check

def reset_service(client, service):
    task_monitor = client.get_task_monitor()
    vm = VM(client, resource=service['resource'])

    print("Powering off...")
    resource = vm.power_off()
    task_monitor.wait_for_success(resource)
    vm.reload()

    print("Restoring snapshot...")
    resource = vm.snapshot_revert_to_current()
    task_monitor.wait_for_success(resource)
    vm.reload()

    print("Powering on...")
    resource = vm.power_on()
    task_monitor.wait_for_success(resource)
    vm.reload()

    print("VM reset finished")

# begin health checks
while True:
    now = str(datetime.datetime.now())
    print(f'Running healthcheck at {now}')
    for service in services:
        name = service['name']
        vm = service['vm']
        if health_check(service):
            print(f'[{Fore.GREEN}OK{Style.RESET_ALL}] {name} ({vm})')
        else:
            print(f'[{Fore.RED}FAIL{Style.RESET_ALL}] {name} ({vm})')
            reset_service(client, service)
    time.sleep(10 * 60)
