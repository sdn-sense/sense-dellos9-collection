#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright: Contributors to the Ansible project
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)
import re
import traceback
from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.six import iteritems
from ansible.utils.display import Display
from ansible_collections.sense.dellos9.plugins.module_utils.network.dellos9 import run_commands, PortMapping
from ansible_collections.sense.dellos9.plugins.module_utils.network.dellos9 import dellos9_argument_spec, check_args

display = Display()


class FactsBase:
    """Base class for Facts"""

    COMMANDS = []

    def __init__(self, module):
        self.module = module
        self.facts = {}
        self.responses = None

    def populate(self):
        """Populate responses"""
        self.responses = run_commands(self.module, self.COMMANDS, check_rc=False)

    def run(self, cmd):
        """Run commands"""
        return run_commands(self.module, cmd, check_rc=False)


class Default(FactsBase):
    """
    Default Class to get basic info.
    Required params for SENSE:
    'info': {'macs': ['4c:76:25:e8:44:c0']}
    """
    COMMANDS = [
        'show system',
    ]

    def populate(self):
        super(Default, self).populate()
        data = self.responses[0]

        self.facts['info'] = {'macs': []}
        systemMac = self.parse_mac(data)
        if systemMac:
            self.facts['info']['macs'].append(systemMac)

    @staticmethod
    def parse_mac(data):
        """Parse version"""
        match = re.search(r'^Stack MAC\s*:\s*(.+)', data)
        if match:
            return match.group(1)
        return ""


class LLDPInfo(FactsBase):
    """LLDP Information and link mapping"""
    COMMANDS = ['show lldp neighbors detail']

    def populate(self):
        super(LLDPInfo, self).populate()
        data = self.responses[0]
        self.facts['lldp'] = {}
        self.getlldpneighbors(data)

    def getlldpneighbors(self, data):
        """
        Get all lldp neighbors. Each entry will contain:
         Local Interface Hu 1/1 has 1 neighbor
          Total Frames Out: 98232
          Total Frames In: 98349
          Total Neighbor information Age outs: 0
          Total Multiple Neighbors Detected: 0
          Total Frames Discarded: 0
          Total In Error Frames: 0
          Total Unrecognized TLVs: 0
          Total TLVs Discarded: 0
          Next packet will be sent after 7 seconds
          The neighbors are given below:
          -----------------------------------------------------------------------
            Remote Chassis ID Subtype: Mac address (4)
            Remote Chassis ID:  34:17:eb:4c:1e:80
            Remote Port Subtype:  Interface name (5)
            Remote Port ID:  hundredGigE 1/32
            Local Port ID: hundredGigE 1/1
            Locally assigned remote Neighbor Index: 2
            Remote TTL:  120
            Information valid for next 113 seconds
            Time since last information change of this neighbor:  2w2d16h
           ---------------------------------------------------------------------------
        """
        regexs = {'local_port_id': r'Local Port ID:\s*(.+)',
                  'remote_system_name': r'Remote System Name:\s*(.+)',
                  'remote_port_id': r'Remote Port ID:\s*(.+)',
                  'remote_chassis_id': r'Remote Chassis ID:\s*(.+)'}
        for entry in data.split('========================================================================'):
            entryOut = {}
            for regName, regex in regexs.items():
                match = re.search(regex, entry, re.M)
                if match:
                    entryOut[regName] = match.group(1)
            if 'local_port_id' in entryOut:
                self.facts['lldp'][entryOut['local_port_id']] = entryOut


class Interfaces(FactsBase):
    """All Interfaces Class"""
    COMMANDS = ['show interfaces',
                'show running-config',
                'show lldp neighbors detail']

    def populate(self):
        super(Interfaces, self).populate()

        self.facts['interfaces'] = {}
        calls = {'description': self.parse_description,
                 'macaddress': self.parse_macaddress,
                 'ipv4': self.parse_ipv4,
                 'ipv6': self.parse_ipv6,
                 'mtu': self.parse_mtu,
                 'bandwidth': self.parse_bandwidth,
                 'mediatype': self.parse_mediatype,
                 'duplex': self.parse_duplex,
                 'lineprotocol': self.parse_lineprotocol,
                 'operstatus': self.parse_operstatus,
                 'type': self.parse_type,
                 'channel-member': self.parse_members}
        interfaceData = self.parseInterfaces(self.responses[0])
        for intfName, intfDict in interfaceData.items():
            intf = {}
            for key in calls:
                tmpOut = calls.get(key)(intfDict)
                if tmpOut:
                    intf[key] = tmpOut
            self.facts['interfaces'][intfName] = intf
        # Use running config to identify all tagged, untagged vlans and mapping
        self.parseRunningConfig(self.responses[1])
        # Also write running config to output
        self.facts['config'] = self.responses[1]

    def parseRunningConfig(self, data):
        """General Parser to parse ansible config"""
        portMapper = PortMapping()
        interfaceSt = False
        key = None
        for line in data.split('\n'):
            line = line.strip()  # Remove all white spaces
            if line == "!" and interfaceSt:
                interfaceSt = False  # This means interface ended!
            elif line.startswith('interface'):
                interfaceSt = True
                key = line[10:]
            elif interfaceSt:
                if line.startswith('tagged') or line.startswith('untagged'):
                    tmpOut = portMapper.parseMembers(line)
                    if tmpOut and key in self.facts['interfaces']:
                        self.facts['interfaces'][key].setdefault(line.split()[0], [])
                        self.facts['interfaces'][key][line.split()[0]] += tmpOut

    @staticmethod
    def parseInterfaces(data):
        """Parse interfaces from output"""
        parsed = {}
        newline_count = 0
        interface_start = True
        key = None
        for line in data.split('\n'):
            if interface_start:
                newline_count = 0
            if len(line) == 0:
                newline_count += 1
                if newline_count == 2:
                    interface_start = True
            else:
                match = re.match(r'^(\S+) (\S+)', line)
                if match and interface_start:
                    interface_start = False
                    key = match.group(0)
                    parsed[key] = line
                else:
                    parsed[key] += '\n%s' % line
        return parsed

    @staticmethod
    def parse_description(data):
        match = re.search(r'Description: (.+)$', data, re.M)
        if match:
            return match.group(1)

    @staticmethod
    def parse_macaddress(data):
        match = re.search(r'address is (\S+)', data)
        if match:
            if match.group(1) != "not":
                return match.group(1)

    @staticmethod
    def parse_ipv4(data):
        match = re.search(r'Internet address is (\S+)', data)
        if match:
            if match.group(1) != "not":
                addr, masklen = match.group(1).split('/')
                return [dict(address=addr, masklen=int(masklen))]

    @staticmethod
    def parse_ipv6(data):
        match = re.search(r'Global IPv6 address: (\S+)', data)
        if match:
            if match.group(1) != "not":
                addr, masklen = match.group(1).split('/')
                return [dict(address=addr, masklen=int(masklen))]

    @staticmethod
    def parse_mtu(data):
        match = re.search(r'MTU (\d+)', data)
        if match:
            return int(match.group(1))

    @staticmethod
    def parse_bandwidth(data):
        match = re.search(r'LineSpeed (\d+)', data)
        if match:
            return int(match.group(1))

    @staticmethod
    def parse_duplex(data):
        match = re.search(r'(\w+) duplex', data, re.M)
        if match:
            return match.group(1)

    @staticmethod
    def parse_mediatype(data):
        media = re.search(r'(.+) media present, (.+)', data, re.M)
        if media:
            match = re.search(r'type is (.+)$', media.group(0), re.M)
            return match.group(1)

    @staticmethod
    def parse_type(data):
        match = re.search(r'Hardware is (.+),', data, re.M)
        if match:
            return match.group(1)

    @staticmethod
    def parse_lineprotocol(data):
        match = re.search(r'line protocol is (\w+[ ]?\w*)\(?.*\)?$', data, re.M)
        if match:
            return match.group(1)

    @staticmethod
    def parse_operstatus(data):
        match = re.search(r'^(?:.+) is (.+),', data, re.M)
        if match:
            return match.group(1)

    @staticmethod
    def parse_members(data):
        keys = {'Hu': 'hundredGigE', 'Fo': 'fortyGigE', 'Te': 'TenGigabitEthernet'}
        match = re.search(r'^Members in this channel: +([a-zA-Z0-9 /\(\)]+)$', data, re.M)
        out = []
        if match:
            allintf = match.group(1).replace('Hu ', 'Hu_').replace('Fo ', 'Fo_').replace('Te ', 'Te_').split()
            for intf in allintf:
                splintf = intf.split('(')[0].split('_')
                if splintf[0] in keys:
                    out.append(f"{keys[splintf[0]]} {splintf[1]}")
        return out


FACT_SUBSETS = {'default': Default,
                'interfaces': Interfaces,
                'lldp': LLDPInfo}

VALID_SUBSETS = frozenset(FACT_SUBSETS.keys())


def main():
    """main entry point for module execution
    """
    argument_spec = {'gather_subset': {'default': ['!config'], 'type': 'list'}}
    argument_spec.update(dellos9_argument_spec)
    module = AnsibleModule(argument_spec=argument_spec,
                           supports_check_mode=True)
    gather_subset = module.params['gather_subset']
    runable_subsets = set()
    exclude_subsets = set()
    try:
    
        for subset in gather_subset:
            if subset == 'all':
                runable_subsets.update(VALID_SUBSETS)
                continue
            if subset.startswith('!'):
                subset = subset[1:]
                if subset == 'all':
                    exclude_subsets.update(VALID_SUBSETS)
                    continue
                exclude = True
            else:
                exclude = False
            if subset not in VALID_SUBSETS:
                module.fail_json(msg='Bad subset')
            if exclude:
                exclude_subsets.add(subset)
            else:
                runable_subsets.add(subset)
        if not runable_subsets:
            runable_subsets.update(VALID_SUBSETS)
    
        runable_subsets.difference_update(exclude_subsets)
        runable_subsets.add('default')
    
        facts = {'gather_subset': [runable_subsets]}
    
        instances = []
        for key in runable_subsets:
            instances.append(FACT_SUBSETS[key](module))
    
        for inst in instances:
            if inst:
                inst.populate()
                facts.update(inst.facts)
    
        ansible_facts = {}
        for key, value in iteritems(facts):
            key = 'ansible_net_%s' % key
            ansible_facts[key] = value
    
        warnings = []
        check_args(module, warnings)
        module.exit_json(ansible_facts=ansible_facts, warnings=warnings)
    except Exception:
        tb = traceback.format_exc()
        display.vvv(tb)
        module.fail_json(tb)


if __name__ == '__main__':
    main()