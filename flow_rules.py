#!/usr/bin/env python3
"""OpenFlow 1.3 FlowMod builder helpers for SecureMediNet."""

from ryu.lib.packet import ether_types
from ryu.ofproto import ofproto_v1_3


def build_drop_rule(datapath, mac, priority=100):
    """Install a DROP rule matching all packets from mac."""
    ofp = datapath.ofproto
    parser = datapath.ofproto_parser
    match = parser.OFPMatch(eth_src=mac)
    instructions = [parser.OFPInstructionActions(ofp.OFPIT_APPLY_ACTIONS, [])]
    mod = parser.OFPFlowMod(
        datapath=datapath,
        priority=priority,
        match=match,
        instructions=instructions,
        command=ofp.OFPFC_ADD,
        idle_timeout=0,
        hard_timeout=0,
    )
    datapath.send_msg(mod)


RATE_LIMIT_KBPS = 512
_METER_ID_BASE = 100


def _mac_to_meter_id(mac):
    last_octet = int(mac.split(":")[-1], 16)
    return _METER_ID_BASE + last_octet


def _install_meter_and_rule(datapath, mac, priority=50):
    ofp = datapath.ofproto
    parser = datapath.ofproto_parser
    meter_id = _mac_to_meter_id(mac)

    bands = [
        parser.OFPMeterBandDrop(
            rate=RATE_LIMIT_KBPS,
            burst_size=64,
        )
    ]
    meter_mod = parser.OFPMeterMod(
        datapath=datapath,
        command=ofp.OFPMC_ADD,
        flags=ofp.OFPMF_KBPS,
        meter_id=meter_id,
        bands=bands,
    )
    datapath.send_msg(meter_mod)

    match = parser.OFPMatch(eth_src=mac)
    instructions = [
        parser.OFPInstructionMeter(meter_id),
        parser.OFPInstructionActions(ofp.OFPIT_APPLY_ACTIONS,
                                     [parser.OFPActionOutput(ofp.OFPP_NORMAL)]),
    ]
    mod = parser.OFPFlowMod(
        datapath=datapath,
        priority=priority,
        match=match,
        instructions=instructions,
        command=ofp.OFPFC_ADD,
        idle_timeout=0,
        hard_timeout=0,
    )
    datapath.send_msg(mod)


def build_rate_limit_rule(datapath, mac, priority=50):
    """Install rate-limiting flow rule via OVS meter. Falls back to drop on error."""
    try:
        _install_meter_and_rule(datapath, mac, priority=priority)
    except Exception:
        build_drop_rule(datapath, mac, priority=priority)


def build_segment_rule(datapath, src_mac, dst_mac, priority=80):
    """Block all packets from src_mac to dst_mac (device-to-device isolation)."""
    ofp = datapath.ofproto
    parser = datapath.ofproto_parser
    match = parser.OFPMatch(eth_src=src_mac, eth_dst=dst_mac)
    instructions = [parser.OFPInstructionActions(ofp.OFPIT_APPLY_ACTIONS, [])]
    mod = parser.OFPFlowMod(
        datapath=datapath,
        priority=priority,
        match=match,
        instructions=instructions,
        command=ofp.OFPFC_ADD,
        idle_timeout=0,
        hard_timeout=0,
    )
    datapath.send_msg(mod)


def delete_drop_rule(datapath, mac, priority=100):
    """Remove a previously installed DROP rule for mac."""
    ofp = datapath.ofproto
    parser = datapath.ofproto_parser
    match = parser.OFPMatch(eth_src=mac)
    mod = parser.OFPFlowMod(
        datapath=datapath,
        priority=priority,
        match=match,
        command=ofp.OFPFC_DELETE,
        out_port=ofp.OFPP_ANY,
        out_group=ofp.OFPG_ANY,
    )
    datapath.send_msg(mod)
