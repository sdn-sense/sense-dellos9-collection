#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Dell OS9 Module unit test
Copyright: Contributors to the SENSE Project
GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

Title                   : sdn-sense/dellos9
Author                  : Justas Balcas
Email                   : juztas (at) gmail.com
@Copyright              : General Public License v3.0+
Date                    : 2023/11/05
"""
__metaclass__ = type

import json
import os
import unittest

from ansible.module_utils import basic
from ansible.module_utils._text import to_bytes


class AnsibleExitJson(Exception):
    """Exception class to be raised by module.exit_json and caught by the
    test case"""


class AnsibleFailJson(Exception):
    """Exception class to be raised by module.fail_json and caught by the
    test case"""


def exit_json(*args, **kwargs):
    """Ansible Exit Json format"""
    if "changed" not in kwargs:
        kwargs["changed"] = False
    raise AnsibleExitJson(kwargs)


def fail_json(*args, **kwargs):
    """Ansible Fail in Json format"""
    kwargs["failed"] = True
    raise AnsibleFailJson(kwargs)


class ModuleTestCase(unittest.TestCase):
    """Module Test Class"""
    def setUp(self):
        """Setup module test"""
        self.mock_module = unittest.mock.patch.multiple(
            basic.AnsibleModule,
            exit_json=exit_json,
            fail_json=fail_json,
        )
        self.mock_module.start()
        self.mock_sleep = unittest.mock.patch("time.sleep")
        self.mock_sleep.start()
        set_module_args({})
        self.addCleanup(self.mock_module.stop)
        self.addCleanup(self.mock_sleep.stop)


def set_module_args(args):
    """Set Module args"""
    if "_ansible_remote_tmp" not in args:
        args["_ansible_remote_tmp"] = "/tmp"
    if "_ansible_keep_remote_files" not in args:
        args["_ansible_keep_remote_files"] = False

    args = json.dumps({"ANSIBLE_MODULE_ARGS": args})
    basic._ANSIBLE_ARGS = to_bytes(args)


fixture_path = os.path.join(os.path.dirname(__file__), "fixtures")
fixture_data = {}


def load_fixture(name):
    """Load fixtures"""
    path = os.path.join(fixture_path, name)

    if path in fixture_data:
        return fixture_data[path]

    with open(path) as f:
        data = f.read()

    try:
        data = json.loads(data)
    except Exception:
        pass

    fixture_data[path] = data
    return data


class TestDellOS9Module(ModuleTestCase):
    """Dell OS9 Test Module"""
    def execute_module(
        self, failed=False, changed=False, commands=None, sort=True, defaults=False
    ):

        self.load_fixtures(commands)

        if failed:
            result = self.failed()
            self.assertTrue(result["failed"], result)
        else:
            result = self.changed(changed)
            self.assertEqual(result["changed"], changed, result)

        if commands is not None:
            if sort:
                self.assertEqual(
                    sorted(commands), sorted(result["updates"]), result["updates"]
                )
            else:
                self.assertEqual(commands, result["updates"], result["updates"])

        return result

    def failed(self):
        with self.assertRaises(AnsibleFailJson) as exc:
            self.module.main()

        result = exc.exception.args[0]
        self.assertTrue(result["failed"], result)
        return result

    def changed(self, changed=False):
        with self.assertRaises(AnsibleExitJson) as exc:
            self.module.main()

        result = exc.exception.args[0]
        self.assertEqual(result["changed"], changed, result)
        return result

    def load_fixtures(self, commands=None):
        pass
