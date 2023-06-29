#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: Contributors to the Ansible project
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)
import re
from ipaddress import ip_address
from ansible.utils.display import Display
from ansible.module_utils._text import to_text
from ansible.module_utils.basic import env_fallback
from ansible.module_utils.connection import exec_command
from ansible_collections.ansible.netcommon.plugins.module_utils.network.common.utils import to_list, ComplexList

display = Display()

_DEVICE_CONFIGS = {}

WARNING_PROMPTS_RE = [
    r"[\r\n]?\[yes/no\]:\s?$",
    r"[\r\n]?\[confirm yes/no\]:\s?$",
    r"[\r\n]?\[y/n\]:\s?$"
]

dellos9_provider_spec = {
    'host': {}, 'port': {'type': int},
    'username': {'fallback': (env_fallback, ['ANSIBLE_NET_USERNAME'])},
    'password': {'fallback': (env_fallback, ['ANSIBLE_NET_PASSWORD']), 'no_log': True},
    'ssh_keyfile': {'fallback': (env_fallback, ['ANSIBLE_NET_SSH_KEYFILE']), 'type': 'path'},
    'authorize': {'fallback': (env_fallback, ['ANSIBLE_NET_AUTHORIZE']), 'type': 'bool'},
    'auth_pass': {'fallback': (env_fallback, ['ANSIBLE_NET_AUTH_PASS']), 'no_log': True},
    'timeout': {'type': 'int'},
}
dellos9_argument_spec = {
    'provider': {'type': 'dict', 'options': dellos9_provider_spec}
}


def check_args(module, warnings):
    """Check args pass"""
    pass


def get_config(module, flags=None):
    """Get running config"""
    flags = [] if flags is None else flags

    cmd = 'show running-config ' + ' '.join(flags)
    cmd = cmd.strip()

    try:
        return _DEVICE_CONFIGS[cmd]
    except KeyError:
        ret, out, err = exec_command(module, cmd)
        if ret != 0:
            module.fail_json(msg='unable to retrieve current config', stderr=to_text(err, errors='surrogate_or_strict'))
        cfg = to_text(out, errors='surrogate_or_strict').strip()
        _DEVICE_CONFIGS[cmd] = cfg
        return cfg


def to_commands(module, commands):
    """Transform commands"""
    spec = {
        'command': {'key': True},
        'prompt': {},
        'answer': {}
    }
    transform = ComplexList(spec, module)
    return transform(commands)


def run_commands(module, commands, check_rc=True):
    """Run Commands"""
    responses = []
    commands = to_commands(module, to_list(commands))
    for cmd in commands:
        cmd = module.jsonify(cmd)
        ret, out, err = exec_command(module, cmd)
        if check_rc and ret != 0:
            module.fail_json(msg=to_text(err, errors='surrogate_or_strict'), rc=ret)
        responses.append(to_text(out, errors='surrogate_or_strict'))
    return responses


def load_config(module, commands):
    """Load config"""
    ret, _out, err = exec_command(module, 'configure terminal')
    if ret != 0:
        module.fail_json(msg='unable to enter configuration mode', err=to_text(err, errors='surrogate_or_strict'))

    for command in to_list(commands):
        if command == 'end':
            continue
        ret, _out, err = exec_command(module, command)
        if ret != 0:
            module.fail_json(msg=to_text(err, errors='surrogate_or_strict'), command=command, rc=ret)

    exec_command(module, 'end')


def normalizedip(ipInput):
    """
    Normalize IPv6 address. It can have leading 0 or not and both are valid.
    This function will ensure same format is used.
    """
    tmp = ipInput.split('/')
    ipaddr = None
    try:
        ipaddr = ip_address(tmp[0]).compressed
    except ValueError:
        ipaddr = tmp[0]
    if len(tmp) == 2:
        return f"{ipaddr}/{tmp[1]}"
    if len(tmp) == 1:
        return ipaddr
    # We return what we get here, because it had multiple / (which is not really valid)
    return ipInput

class PortMapping():

    def __init__(self):
        self.regexs = [r'^tagged (.+) (.+)',
                       r'^untagged (.+) (.+)',
                       r'^channel-member (.+) (.+)',
                       r'^(Port-channel) (.+)']

    @staticmethod
    def _portSplitter(portName, inPorts):
        """Port splitter for dellos9"""
        def __identifyStep():
            if portName == 'fortyGigE':
                return 4
            return 1

        def rule0(reMatch):
            """Rule 0 to split ports to extended list
            INPUT: ('2,18-21,100,122', ',122', '122', '21')
            Split by comma, and loop:
              if no split - add to list
              if exists - split by dash and check if st < en
                every step is 1, 40G - is 4"""
            out = []
            for vals in reMatch[0].split(','):
                if '-' in vals:
                    stVal, enVal = vals.split('-')[0], vals.split('-')[1]
                    if int(stVal) > int(enVal):
                        continue
                    for val in range(int(stVal), int(enVal)+1, __identifyStep()):
                        out.append(val)
                else:
                    out.append(int(vals))
            return out

        def rule1(reMatch):
            """Rule 1 to split ports to extended list
            INPUT: ('1/1-1/2,1/3,1/4,1/10-1/20', ',1/10-1/20', '1/10-1/20', '-1/20')
            Split by comma and loop:
            if no -, add to list
            if - exists - split by dash, split by / and identify which value is diff
            diff values check if st < en and push to looper;
            every step is 1, 40G - is 4"""
            out = []
            for vals in reMatch[0].split(','):
                if '-' in vals:
                    stVal, enVal = vals.split('-')[0].split('/'), vals.split('-')[1].split('/')
                    mod, modline = None, None
                    # If first digit not equal - replace first
                    if stVal[0] != enVal[0] and stVal[1] == enVal[1] and \
                       int(stVal[0]) < int(enVal[0]):
                        modline = "%%s/%s" % stVal[1]
                        mod = 0
                    # If second digit not equal - replace second
                    elif stVal[0] == enVal[0] and stVal[1] != enVal[1] and \
                         int(stVal[1]) < int(enVal[1]):
                        modline = "%s/%%s" % stVal[0]
                        mod = 1
                    if mod and modline:
                        for val in range(int(stVal[mod]), int(enVal[mod])+1, __identifyStep()):
                            out.append(modline % val)
                else:
                    out.append(vals)
            return out

        def rule2(reMatch):
            """Rule 2 to split ports to extended list
            INPUT ('0', '0-3,11-12,15,56,58-59', ',58-59', '58', '59')
            Split by comma and loop:
            if no -, add to list
            if - exists - split by dash, and check if st < en
            every step is 1, 40G - is 4"""
            out = []
            tmpOut = rule0(tuple([reMatch[1]]))
            for line in tmpOut:
                out.append(f"{reMatch[0]}/{line}")
            return out

        def rule3(reMatch):
            """Rule 3 to split ports to extended list
            INPUT ('1/6/1-1/8/1,1/9/1,1/10/1-1/20/1', ',1/10/1-1/20/1', '1/10/1', '1', '10', '1', '1/20/1', '1', '20', '1')
            Split by comma and loop:
            if no -, add to list
            if - exists - split by dash, split by / and identify which value is diff
            diff values check if st < en and push to looper;
            Here all step is 1, even 40G is 1;"""
            out = []
            for vals in reMatch[0].split(','):
                if '-' in vals:
                    stVal, enVal = vals.split('-')[0].split('/'), vals.split('-')[1].split('/')
                    mod, modline = None, None
                    # If first digit not equal - replace first
                    if stVal[0] != enVal[0] and stVal[1] == enVal[1] and \
                       stVal[2] == enVal[2] and int(stVal[0]) < int(enVal[0]):
                        modline = "%%s/%s/%s" % (stVal[1], stVal[2])
                        mod = 0
                    # If second digit not equal - replace second
                    elif stVal[0] == enVal[0] and stVal[1] != enVal[1] and \
                         stVal[2] == enVal[2] and int(stVal[1]) < int(enVal[1]):
                        modline = "%s/%%s/%s" % (stVal[0], stVal[2])
                        mod = 1
                    # If third digit not equal - replace third
                    elif stVal[0] == enVal[0] and stVal[1] == enVal[1] and \
                         stVal[2] != enVal[2] and int(stVal[2]) < int(enVal[2]):
                        modline = "%s/%s/%%s" % (stVal[0], stVal[1])
                        mod = 2
                    if mod and modline:
                        for val in range(int(stVal[mod]), int(enVal[mod])+1, 1):
                            out.append(modline % val)
                else:
                    out.append(vals)
            return out


        # Rule 0: Parses digit or digit group separated with dash.
        # Can be multiple separated by comma:
        match = re.match(r'((,*(\d{1,3}-*(\d{1,3})*))+)$', inPorts)
        if match:
            return rule0(match.groups())
        # Rule 1: Parses only this group below, can be multiple separated by comma:
        # 1/1
        # 1/1-1/2
        match = re.match(r'((,*(\d{1,3}/\d{1,3}(-\d{1,3}/\d{1,3})*))+)$', inPorts)
        if match:
            return rule1(match.groups())
        # Rule 2: 0/XX, where XX can be digit or 2 digits separated by dash.
        # Afterwards joint by comma, digit or 2 digits separated by dash:
        match = re.match(r'(\d{1,3})/((,*(\d{1,3})-*(\d{1,3})*)+)$', inPorts)
        if match:
            return rule2(match.groups())
        # Rule 3: Parses only this group below, can be multiple separated by comma:
        # 1/1/1
        # 1/7/1-1/8/1
        match = re.match(r'((,*((\d{1,3})/(\d{1,3})/(\d{1,3}))-*((\d{1,3})/(\d{1,3})/(\d{1,3}))*)+)$', inPorts)
        if match:
            return rule3(match.groups())

        # If we are here - raise WARNING, and continue. Return empty list
        #self.logger.debug('WARNING. Line %s %s NOT MATCHED' % (portName, inPorts))
        return []

    def parseMembers(self, line):
        """Parse Members of port"""
        out = []
        for regex in self.regexs:
            match = re.search(regex, line)
            if match:
                tmpout = self._portSplitter(match.group(1), match.group(2))
                if not tmpout:
                    return out
                for item in tmpout:
                    out.append(f"{match.group(1)} {item}")
        return out