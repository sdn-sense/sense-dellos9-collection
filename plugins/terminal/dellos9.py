#!/usr/bin/python
# -*- coding: utf-8 -*-
"""Dell OS 9 Terminal Module
Copyright: Contributors to the SENSE Project
GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

Title                   : sdn-sense/sense-dellos9-collection
Author                  : Justas Balcas
Email                   : juztas (at) gmail.com
@Copyright              : General Public License v3.0+
Date                    : 2023/11/05
"""
import json
import re

from ansible.errors import AnsibleConnectionFailure
from ansible.module_utils._text import to_bytes, to_text
from ansible.plugins.terminal import TerminalBase
from ansible_collections.sense.dellos9.plugins.module_utils.runwrapper import classwrapper

@classwrapper
class TerminalModule(TerminalBase):
    """
    Terminal Module to control cli, prompt, shell, become
    on devices via ansible.
    """

    terminal_stdout_re = [
        re.compile(rb"[\r\n]?[\w+\-\.:\/\[\]]+(?:\([^\)]+\)){,3}(?:>|#) ?$"),
        re.compile(rb"\[\w+\@[\w\-\.]+(?: [^\]])\] ?[>#\$] ?$"),
    ]

    terminal_stderr_re = [
        re.compile(
            rb"% ?Error: (?:(?!\bdoes not exist\b)(?!\balready exists\b)(?!\bHost not found\b)(?!\bnot active\b).)*\n"
        ),
        re.compile(rb"% ?Bad secret"),
        re.compile(rb"invalid input", re.I),
        re.compile(rb"(?:incomplete|ambiguous) command", re.I),
        re.compile(rb"connection timed out", re.I),
        re.compile(rb"'[^']' +returned error code: ?\d+"),
    ]

    terminal_initial_prompt = rb"\[y/n\]:"

    terminal_initial_answer = b"y"

    def _exec_cli_command(self, cmd, check_rc=True):
        """
        Executes the CLI command on the remote device and returns the output
        :arg cmd: Byte string command to be executed
        """
        return self._connection.exec_command(cmd)

    def _get_prompt(self):
        """
        Returns the current prompt from the device
        :returns: A byte string of the prompt
        """
        return self._connection.get_prompt()

    def on_open_shell(self):
        """Called after the SSH session is established

        This method is called right after the invoke_shell() is called from
        the Paramiko SSHClient instance.  It provides an opportunity to setup
        terminal parameters such as disabling paging for instance.
        """
        try:
            self._exec_cli_command(b"terminal length 0")
        except AnsibleConnectionFailure:
            raise AnsibleConnectionFailure(
                "unable to set terminal parameters"
            ) from AnsibleConnectionFailure

    def on_close_shell(self):
        """Called before the connection is closed

        This method gets called once the connection close has been requested
        but before the connection is actually closed.  It provides an
        opportunity to clean up any terminal resources before the shell is
        actually closed
        """

    def on_become(self, passwd=None):
        """Called when privilege escalation is requested

        :kwarg passwd: String containing the password

        This method is called when the privilege is requested to be elevated
        in the play context by setting become to True.  It is the responsibility
        of the terminal plugin to actually do the privilege escalation such
        as entering `enable` mode for instance
        """
        if self._get_prompt().endswith(b"#"):
            return

        cmd = {"command": "enable"}
        if passwd:
            cmd["prompt"] = to_text(r"[\r\n]?password: $", errors="surrogate_or_strict")
            cmd["answer"] = passwd

        try:
            self._exec_cli_command(
                to_bytes(json.dumps(cmd), errors="surrogate_or_strict")
            )
        except AnsibleConnectionFailure:
            raise AnsibleConnectionFailure(
                "unable to elevate privilege to enable mode"
            ) from AnsibleConnectionFailure

    def on_unbecome(self):
        """Called when privilege deescalation is requested

        This method is called when the privilege changed from escalated
        (become=True) to non escalated (become=False).  It is the responsibility
        of this method to actually perform the deauthorization procedure
        """
        prompt = self._get_prompt()
        if prompt is None:
            # if prompt is None most likely the terminal is hung up at a prompt
            return

        if prompt.strip().endswith(b")#"):
            self._exec_cli_command(b"end")
            self._exec_cli_command(b"disable")

        elif prompt.endswith(b"#"):
            self._exec_cli_command(b"disable")
