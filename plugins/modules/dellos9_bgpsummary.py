#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Dell OS 9 BGP Summary
Copyright: Contributors to the SENSE Project
GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

Dell OS9 has no JSON/XML output for BGP at all (confirmed live: the only
'| ?' pipe options are except/find/grep/no-more/save), so this runs two
plain-text commands per AFI and regex-parses both:
  show ip bgp [vrf <vrf>] [ipv6 unicast] summary     -> device-wide local ASN
  show ip bgp [vrf <vrf>] [ipv6 unicast] neighbors   -> per-peer state,
                                                         remote ASN, and
                                                         accepted/advertised
                                                         prefix counts (both
                                                         directions are
                                                         present in this one
                                                         command, even for
                                                         down peers)

Normalizes into the shared SiteRM BGP schema:
{"vrf": ..., "afi_checked": [...], "peers": [...]}

Title                   : sdn-sense/sense-dellos9-collection
Author                  : Justas Balcas
Email                   : juztas (at) gmail.com
@Copyright              : General Public License v3.0+
Date                    : 2026/09/15
"""
from __future__ import (absolute_import, division, print_function)

__metaclass__ = type

import re

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.sense.dellos9.plugins.module_utils.network.dellos9 import run_commands
from ansible_collections.sense.dellos9.plugins.module_utils.network.dellos9 import dellos9_argument_spec, check_args
from ansible_collections.sense.dellos9.plugins.module_utils.runwrapper import functionwrapper

_KNOWN_STATES = ("established", "idle", "active", "connect", "opensent", "openconfirm")


@functionwrapper
def normalizeBgpState(rawstate):
    """Normalize a vendor BGP FSM state string to the shared enum."""
    state = str(rawstate).lower()
    return state if state in _KNOWN_STATES else "unknown"


@functionwrapper
def durationToSeconds(rawduration):
    """Convert Dell OS9 duration text (e.g. '00:00:00' or '6w4d:10:21:12')
    to seconds. Returns None if unparsable."""
    if not rawduration:
        return None
    weeks = days = 0
    match = re.match(r"(?:(\d+)w)?(?:(\d+)d)?(\d+):(\d+):(\d+)$", rawduration.strip())
    if not match:
        return None
    wtxt, dtxt, htxt, mtxt, stxt = match.groups()
    weeks = int(wtxt) if wtxt else 0
    days = int(dtxt) if dtxt else 0
    return ((weeks * 7 + days) * 24 * 3600) + (int(htxt) * 3600) + (int(mtxt) * 60) + int(stxt)


@functionwrapper
def buildCommand(vrf, iptype, subcommand):
    """Build the Dell OS9 'show ip bgp ...' command for a single AFI."""
    vrfclause = f"vrf {vrf} " if vrf else ""
    afi = "ipv6 unicast " if iptype == "ipv6" else ""
    return f"show ip bgp {vrfclause}{afi}{subcommand}"


@functionwrapper
def parseLocalAsn(summarytext):
    """Extract the device-wide local AS number from 'summary' output."""
    match = re.search(r"local AS number (\d+)", summarytext)
    return int(match.group(1)) if match else None


@functionwrapper
def parseNeighborsText(neighborstext, iptype, localasn, peers):
    """Parse 'neighbors' output, appending one normalized peer per block."""
    blocks = re.split(r"(?=^BGP neighbor is )", neighborstext, flags=re.M)
    for block in blocks:
        headermatch = re.search(r"^BGP neighbor is ([^\s,]+),\s*remote AS (\d+)", block, re.M)
        if not headermatch:
            continue
        statematch = re.search(r"BGP state (\S+),\s*in this state for (\S+)", block)
        acceptedmatch = re.search(r"Prefixes accepted (\d+)", block)
        advertisedmatch = re.search(r"Prefixes advertised (\d+)", block)
        peers.append({
            "peer": headermatch.group(1),
            "iptype": iptype,
            "local_asn": localasn,
            "remote_asn": int(headermatch.group(2)),
            "state": normalizeBgpState(statematch.group(1) if statematch else ""),
            "uptime_seconds": durationToSeconds(statematch.group(2)) if statematch else None,
            "prefixes_received": int(acceptedmatch.group(1)) if acceptedmatch else None,
            "prefixes_advertised": int(advertisedmatch.group(1)) if advertisedmatch else None,
            "advertised_known": True,
        })


@functionwrapper
def main():
    """main entry point for module execution"""
    argument_spec = {
        "vrf": {"type": "str", "default": ""},
        "type": {"type": "str", "default": "both", "choices": ["ipv4", "ipv6", "both"]},
    }
    argument_spec.update(dellos9_argument_spec)

    module = AnsibleModule(argument_spec=argument_spec, supports_check_mode=True)

    warnings = []
    check_args(module, warnings)

    vrf = module.params["vrf"]
    wanttype = module.params["type"]
    wantafis = ["ipv4", "ipv6"] if wanttype == "both" else [wanttype]

    peers = []
    localasn = None
    for iptype in wantafis:
        summaryresp = run_commands(module, [buildCommand(vrf, iptype, "summary")])
        neighborsresp = run_commands(module, [buildCommand(vrf, iptype, "neighbors")])
        thisasn = parseLocalAsn(summaryresp[0] if summaryresp else "")
        if thisasn is not None:
            localasn = thisasn
        parseNeighborsText(neighborsresp[0] if neighborsresp else "", iptype, localasn, peers)

    bgp_summary = {"vrf": vrf or None, "afi_checked": wantafis, "peers": peers}

    module.exit_json(changed=False, warnings=warnings, bgp_summary=bgp_summary)


if __name__ == "__main__":
    main()
