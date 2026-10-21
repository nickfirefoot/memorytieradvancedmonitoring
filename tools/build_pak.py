#!/usr/bin/env python3
"""Assemble the content-only pak: dashboard + super metrics, no adapter.

A pak is a zip. Layout mirrors the real VsanHostMetrics pak on this machine and what
mp_build.py produces (LESSONS.md §3): the whole content/ tree ships, dashboards go in a
pre-created, case-preserved subdirectory, views would go in content/reports/.

    manifest.txt                        adapters: [] / adapter_kinds: []  -> content-only
    eula.txt  pak_icon.png
    resources/resources.properties      DISPLAY_NAME / DESCRIPTION / VENDOR
    content/dashboards/<Name>/<Name>.json
    content/supermetrics/<name>.json

Two deliberate differences from the UI-import zip built by build_content.py:
  * the in-pak dashboard carries `adapterName` = the pak's manifest name. Operations rewrote
    that field to the pak name on save for the vSAN pack; whether a content-only pak needs it
    is [unknown] (LESSONS.md 1.5). Real UI exports do not carry it, so the UI zip stays clean.
  * the super metrics ride inside the pak instead of a separate import step.

Bump VERSION for every reinstall (BACKLOG.md §6).

Usage:  python3 build_content.py && python3 build_pak.py
"""
import json
import io
import os
import re
import struct
import sys
import zipfile
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
BUILD = os.path.join(HERE, "build")

VERSION = "2.1.5"      # 2.1.5: new icon, Active_GB from a built-in metric, receiver heat map removed (server error), adapter sends no relationships. 2.1.4: selectable cluster overview at the top, sizing detail as a receiver, fixed 30-day windows. 2.1.3: text panels as self-contrasting cards for light and dark themes, rewritten help. 2.1.2: dashboards defined vSphere World in entries.resource (providers timed out), custom group in content-import shape, heatmap follows selection, text panels styled. 2.1.1: adapter.zip stored files before their directories, so 2.1.0 failed at APPLY_ADAPTER. 2.1.0: Export for MTAT dashboard, fleet-rollup binding fix. 2.0.0: real collector, two dashboards, opt-in group
IMAGE_REGISTRY = "ghcr.io"
IMAGE_REPOSITORY = "/nickfirefoot/memorytieradvancedmonitoring"
IMAGE_DIGEST = "sha256:f022578468f00c836447ce872784fab479b15a22855d3865ae70c405a9f44cfe"
PAK_NAME = "MemoryTierAdvanced"           # manifest "name"; also injected as adapterName
KIND_KEY = "MemTierAdvanced"                 # a REAL adapter now: collects the tiering disqualifiers
DISPLAY_NAME = "Memory Tier Advanced"
VENDOR = "Nick Wilson"
DESCRIPTION = ("Sizes a vSphere estate for VCF 9 NVMe memory tiering from metrics the vCenter "
               "adapter already collects. Content only: dashboards and super metrics, no "
               "adapter, no image, no registry. Target: Operations 8.18 and later.")
DASH_DIR = "Memory_Tier_Advanced_Clusters"
REFRESH_DIR = "Memory_Tier_Advanced_Hardware_Refresh"   # pre-created so mp_build-style lowercasing never applies
MTAT_DIR = "Memory_Tier_Advanced_Export_for_MTAT"

# Mirrors manifest.txt of the real pak on this host; only the adapter fields change.
MANIFEST = {
    "display_name": "DISPLAY_NAME",
    "name": PAK_NAME,
    "description": "DESCRIPTION",
    "version": VERSION,
    "vcops_minimum_version": "8.10.0",      # proven to install on 9.1.1; below the 8.18 target
    "disk_space_required": 10,
    "run_scripts_on_all_nodes": "true",
    "eula_file": "eula.txt",
    "platform": ["Linux Non-VA", "Linux VA"],
    "vendor": VENDOR,
    "pak_icon": "pak_icon.png",
    "pak_validation_script": {"script": ""},
    "adapter_pre_script": {"script": ""},
    "adapter_post_script": {"script": ""},
    "adapters": ["adapter.zip"],
    "adapter_kinds": [KIND_KEY],
    "license_type": "",
}

# REVIEW BEFORE SHIPPING: licence terms are the author's call, not the generator's. This is a
# plain-language placeholder that is at least not an empty agreement box (BACKLOG.md §6).
EULA = f"""{DISPLAY_NAME.upper()} — CONTENT PACK FOR VCF OPERATIONS
END USER LICENSE AGREEMENT

Copyright 2026 {VENDOR}

This content pack contains dashboards and super metric definitions only. It installs no
adapter, runs no code on the Operations appliance or Cloud Proxy, and collects no data of its
own; every figure it shows is computed from metrics the built-in vCenter adapter already
collects.

You may install, use, modify and redistribute this content pack, provided this notice is kept
with it.

IT IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND. The figures it produces are sizing
estimates derived from sampled metrics and are not a substitute for a capacity assessment
by a qualified engineer. The author accepts no liability for purchasing or configuration
decisions made on the basis of this content.

Not affiliated with or endorsed by Broadcom or VMware.
"""

RESOURCES = f"""#Default localization file.

#The solution's localized name displayed in UI
DISPLAY_NAME={DISPLAY_NAME}

#The solution's localized description
DESCRIPTION={DESCRIPTION}

#The vendor's localized name
VENDOR={VENDOR}
"""

NAME_AUDIT = re.compile(
    r"esxi[0-9]+|vc[0-9]+\b|ops[0-9]+\b|mgmt[0-9]|denick|[a-z0-9-]+\.lab\b|"
    r"\b[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\b|\bhost-[0-9]+|domain-c[0-9]+", re.I)


def png_icon(size=128, rgb=(0x2E, 0x6F, 0xA7)):
    """A flat PNG with no dependencies. Replace with real artwork when there is some."""
    raw = b"".join(b"\x00" + bytes(rgb) * size for _ in range(size))
    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b""))


def write_parents_first(zf, entries, last=()):
    """Write (name, data) entries so every directory entry precedes everything inside it.
    data None means a bare directory. The installer extracts in STORED order and creates a
    directory only when it reaches that directory's own entry: 2.1.0 stored
    resources/resources.properties ahead of resources/ and failed at APPLY_ADAPTER with
    NoSuchFileException (analytics log, 2026-10-21 03:43:01). The netstats pak, which
    installs, stores each directory immediately before its first child."""
    written = set()

    def ensure(path):
        parts = path.rstrip("/").split("/")
        for i in range(1, len(parts) + (1 if path.endswith("/") else 0)):
            d = "/".join(parts[:i]) + "/"
            if d not in written:
                zf.writestr(zipfile.ZipInfo(d), b"")
                written.add(d)

    # Root files first, then trees; `last` names go at the very end, as adapter.zip does in
    # the netstats pak that installs.
    order = sorted(entries, key=lambda e: (e[0] in last, e[0].count("/") > 0, e[0]))
    for name, data in order:
        ensure(name)
        if data is not None:
            zf.writestr(name, data)


def children_before_parents(blob):
    """Entries whose parent directory entry is stored later or not at all."""
    seen, bad = set(), []
    for n in zipfile.ZipFile(io.BytesIO(blob)).namelist():
        parent = n.rstrip("/").rpartition("/")[0]
        if parent and parent + "/" not in seen:
            bad.append(n)
        seen.add(n if n.endswith("/") else n + "#")
    return bad


def describe_drift(describe_xml):
    """Differences between describe.xml and the adapter's own adapter_definition(), by kind
    and attribute key. Needs the Integration SDK library to import the adapter; without it the
    check is reported as skipped rather than silently passed."""
    import importlib.util
    import xml.etree.ElementTree as ET
    path = os.path.join(os.path.dirname(HERE), "adapter", "app", "adapter.py")
    saved = sys.argv
    # The SDK library reads sys.argv[-2] / [-1] as pipe paths at IMPORT time, as defaults.
    sys.argv = [saved[0], "", ""]
    try:
        spec = importlib.util.spec_from_file_location("memtier_adapter", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        code = mod.adapter_definition().to_json()
    except ImportError as e:
        sys.argv = saved
        print(f"   describe/adapter_definition comparison SKIPPED: {e} "
              f"(run with ~/.mp/bin/python3 to include it)")
        return []
    sys.argv = saved
    ns = "{http://schemas.vmware.com/vcops/schema}"
    root = ET.fromstring(describe_xml.encode())
    in_xml = {rk.get("key"): {a.get("key") for a in rk.findall(f"{ns}ResourceAttribute")}
              for rk in root.iter(f"{ns}ResourceKind") if rk.get("type") != "7"}
    in_code = {}
    for o in code.get("object_types", code.get("objectTypes", [])):
        key = o.get("key")
        attrs = set()
        for group in ("properties", "metrics", "attributes"):
            attrs |= {a.get("key") for a in o.get(group, [])}
        in_code[key] = attrs
    problems = []
    for kind in sorted(set(in_xml) | set(in_code)):
        a, b = in_xml.get(kind), in_code.get(kind)
        if a is None or b is None:
            problems.append(f"object kind {kind!r} is in {'code' if a is None else 'describe.xml'} only")
        elif a != b:
            problems.append(f"{kind}: describe.xml lacks {sorted(b - a)}, code lacks {sorted(a - b)}")
    return problems


def main():
    dash_src = os.path.join(BUILD, "dashboard.json")
    sm_src = os.path.join(BUILD, "supermetric.json")
    for f in (dash_src, sm_src):
        if not os.path.exists(f):
            print(f"missing {f} — run build_content.py first", file=sys.stderr)
            return 1

    dash = json.load(open(dash_src))
    refresh = json.load(open(os.path.join(BUILD, "dashboard-refresh.json")))
    mtat = json.load(open(os.path.join(BUILD, "dashboard-mtat.json")))
    # In-pak dashboards use the CONTENT-EXPORT shape, not the UI-export shape. Every dashboard
    # in the vCommunity pak (SDK-built, installed widely) carries adapterName, namePath,
    # docCenterKey, temporary, widgetInteractions, columnCount 1 and columnProportion "1-1" --
    # the exact fields the vSAN pack found absent from UI exports. Both observations are right;
    # they are two formats. The UI-import zip from build_content.py stays in the UI shape.
    for d in dash["dashboards"] + refresh["dashboards"] + mtat["dashboards"]:
        d["adapterName"] = PAK_NAME
        d["namePath"] = DISPLAY_NAME                       # groups the dashboard under a folder
        short = d["name"].replace(f"{DISPLAY_NAME} - ", "")  # "… - Clusters" -> "Clusters"
        d["name"] = f"{DISPLAY_NAME}/{short}"               # vCommunity: "vCommunity/<Dashboard>"
        d["docCenterKey"] = f"{KIND_KEY.lower()}_{int(d['id'][:3], 16) % 1000:03d}"  # deterministic from the uuid5 id
        d["temporary"] = False
        d.setdefault("widgetInteractions", [])
        d["columnCount"] = 1
        d["columnProportion"] = "1-1"
        d.pop("editAllowed", None)                         # UI-export-only field
    sms = json.load(open(sm_src))

    manifest_bytes = json.dumps(MANIFEST, indent=4).encode()
    # The real icon (2026-10-21), 256x256 as both working paks on the lab carry. The generated
    # flat square remains only as a fallback if the file is missing.
    icon_path = os.path.join(HERE, "pak_icon.png")
    icon = open(icon_path, "rb").read() if os.path.exists(icon_path) else png_icon()

    # v0.3.0: content import is adapter-shaped (LESSONS.md 4.7; SDK source read by the vSAN
    # session), and describeSchema.xsd makes an AdapterKind REQUIRE at least one ResourceKind.
    # So the pak declares one schema-only adapter kind with a single adapter-instance kind
    # (type="7") that has no identifiers, no credential and no container pointer -- nothing to
    # configure, nothing that can run, exists only so the installer registers a solution and
    # reaches content/. This is how pre-SDK community content paks were distributed.
    # adapter.zip mirrors the real VsanHostMetrics pak member for member, minus <Kind>.conf.
    # The adapter COLLECTS now, so describe.xml declares what it publishes: an adapter
    # instance kind (type 7) carrying the connection parameters, a credential kind, and the two
    # object kinds that hold the disqualifiers. nameKey values index resources.properties.
    describe = f"""<?xml version='1.0' encoding='UTF-8'?>
<AdapterKind xmlns="http://schemas.vmware.com/vcops/schema" key="{KIND_KEY}" nameKey="1" version="1">
  <CredentialKinds>
    <CredentialKind key="memtier_vc_credential" nameKey="20">
      <CredentialField key="vcenter_password" nameKey="21" required="true" dispOrder="0" password="true" enum="false" type="string"/>
    </CredentialKind>
  </CredentialKinds>
  <ResourceKinds>
    <ResourceKind key="{KIND_KEY}_adapter_instance" nameKey="2" type="7" credentialKind="memtier_vc_credential">
      <ResourceIdentifier default="" key="vcenter_host" nameKey="3" required="true" dispOrder="0" enum="false" type="string" identType="1"/>
      <ResourceIdentifier default="" key="vcenter_user" nameKey="4" required="true" dispOrder="1" enum="false" type="string" identType="1"/>
      <ResourceIdentifier default="false" key="verify_certs" nameKey="5" required="true" dispOrder="2" enum="true" type="string" identType="1">
        <enum value="true" nameKey="6" default="false"/>
        <enum value="false" nameKey="7" default="true"/>
      </ResourceIdentifier>
    </ResourceKind>
    <ResourceKind key="MemTierAdvancedVM" nameKey="8" type="1">
      <ResourceIdentifier default="" key="vm_moref" nameKey="9" required="true" dispOrder="0" enum="false" type="string" identType="1"/>
      <ResourceIdentifier default="" key="vc_uuid" nameKey="10" required="true" dispOrder="1" enum="false" type="string" identType="1"/>
      <ResourceAttribute key="pinned" nameKey="11" unit="" dashboardOrder="0" dataType="float" isProperty="false" isRate="false" isDiscrete="true" isImpact="false" defaultMonitored="true" keyAttribute="true"/>
      <ResourceAttribute key="pinnedMemoryKB" nameKey="12" unit="kilobytes" dashboardOrder="1" dataType="float" isProperty="false" isRate="false" isDiscrete="false" isImpact="false" defaultMonitored="true" keyAttribute="false"/>
      <ResourceAttribute key="lpage1GB" nameKey="13" unit="" dashboardOrder="2" dataType="string" isProperty="true" isRate="false" isDiscrete="true" isImpact="false" defaultMonitored="true" keyAttribute="false"/>
      <ResourceAttribute key="lpageEnabled" nameKey="14" unit="" dashboardOrder="3" dataType="string" isProperty="true" isRate="false" isDiscrete="true" isImpact="false" defaultMonitored="true" keyAttribute="false"/>
      <ResourceAttribute key="mmuLargePagesDisabled" nameKey="15" unit="" dashboardOrder="4" dataType="string" isProperty="true" isRate="false" isDiscrete="true" isImpact="false" defaultMonitored="true" keyAttribute="false"/>
      <ResourceAttribute key="latencySensitivity" nameKey="16" unit="" dashboardOrder="5" dataType="string" isProperty="true" isRate="false" isDiscrete="true" isImpact="false" defaultMonitored="true" keyAttribute="false"/>
      <ResourceAttribute key="memoryReservationLockedToMax" nameKey="17" unit="" dashboardOrder="6" dataType="string" isProperty="true" isRate="false" isDiscrete="true" isImpact="false" defaultMonitored="true" keyAttribute="false"/>
      <ResourceAttribute key="passthroughDevices" nameKey="18" unit="" dashboardOrder="7" dataType="string" isProperty="true" isRate="false" isDiscrete="true" isImpact="false" defaultMonitored="true" keyAttribute="false"/>
      <ResourceAttribute key="numaNodeAffinity" nameKey="19" unit="" dashboardOrder="8" dataType="string" isProperty="true" isRate="false" isDiscrete="true" isImpact="false" defaultMonitored="true" keyAttribute="false"/>
      <ResourceAttribute key="pinReason" nameKey="29" unit="" dashboardOrder="9" dataType="string" isProperty="true" isRate="false" isDiscrete="true" isImpact="false" defaultMonitored="true" keyAttribute="false"/>
    </ResourceKind>
    <ResourceKind key="MemTierAdvancedHost" nameKey="22" type="1">
      <ResourceIdentifier default="" key="host_moref" nameKey="23" required="true" dispOrder="0" enum="false" type="string" identType="1"/>
      <ResourceIdentifier default="" key="vc_uuid" nameKey="24" required="true" dispOrder="1" enum="false" type="string" identType="1"/>
      <ResourceAttribute key="Mem_AllocGuestLargePage" nameKey="25" unit="" dashboardOrder="0" dataType="string" isProperty="true" isRate="false" isDiscrete="true" isImpact="false" defaultMonitored="true" keyAttribute="false"/>
      <ResourceAttribute key="LPage_LPageAlwaysTryForNPT" nameKey="26" unit="" dashboardOrder="1" dataType="string" isProperty="true" isRate="false" isDiscrete="true" isImpact="false" defaultMonitored="true" keyAttribute="false"/>
      <ResourceAttribute key="LPage_LPageDefragEnable" nameKey="27" unit="" dashboardOrder="2" dataType="string" isProperty="true" isRate="false" isDiscrete="true" isImpact="false" defaultMonitored="true" keyAttribute="false"/>
      <ResourceAttribute key="LPage_MaxSharedPages" nameKey="28" unit="" dashboardOrder="3" dataType="string" isProperty="true" isRate="false" isDiscrete="true" isImpact="false" defaultMonitored="true" keyAttribute="false"/>
    </ResourceKind>
  </ResourceKinds>
</AdapterKind>
"""
    inner_props = "\n".join([
        f"1 = {DISPLAY_NAME}", f"2 = {DISPLAY_NAME} Adapter Instance",
        "3 = vCenter Server",
        "3.description = FQDN of the vCenter Server. An IP works only with certificate verification off.",
        "4 = vCenter username",
        "4.description = Must include the domain, e.g. user@vsphere.local. READ-ONLY is sufficient: this adapter only reads configuration and never writes.",
        "5 = Verify vCenter certificate", "6 = true", "7 = false",
        "8 = Memory Tier VM Configuration", "9 = VM MoRef", "10 = vCenter UUID",
        "11 = Pinned to DRAM", "11.description = 1 when the VM cannot be tiered: 1GB pages, latency sensitivity high, locked reservation, PCI passthrough or vGPU, or a full reservation.",
        "12 = Pinned memory", "13 = 1GB pages", "14 = Large pages enabled",
        "15 = MMU large pages disabled", "16 = Latency sensitivity",
        "17 = Reservation locked to max", "18 = Passthrough devices", "19 = NUMA node affinity",
        "20 = vCenter credential", "21 = vCenter password",
        "22 = Memory Tier Host Configuration", "23 = Host MoRef", "24 = vCenter UUID",
        "25 = Mem.AllocGuestLargePage", "26 = LPage.LPageAlwaysTryForNPT",
        "27 = LPage.LPageDefragEnable", "28 = LPage.MaxSharedPages",
        "29 = Pin reason", "29.description = Which condition pins this VM to DRAM, or none.", ""])
    # describe.xml is written by hand here, while the adapter declares the same model in
    # adapter_definition(). mp-build generates one from the other; this build does not, so
    # the two can drift with nothing to notice -- a property the adapter sends that describe
    # does not declare. Compare them on every build.
    drift = describe_drift(describe)
    if drift:
        for d in drift:
            print("SELF-CHECK FAILED:", d, file=sys.stderr)
        return 1
    major, minor, impl = VERSION.split(".")
    version_txt = f"Major-Version={major}\nMinor-Version={minor}\nImplementation-Version={impl}\n"
    xsd_src = os.path.join(HERE, "describeSchema.xsd")
    if not os.path.exists(xsd_src):
        print("missing describeSchema.xsd beside build_pak.py (copy from a real pak)", file=sys.stderr)
        return 1
    # v1.0.0: mirror the real pak member for member. v0.3.0 proved a valid describe.xml is
    # never read without <Kind>.conf -- the installer appears to DISCOVER the adapter from
    # KINDKEY= in that file and only then open <KINDKEY>/conf/describe.xml. This .conf carries
    # the kind and API lines only; REGISTRY/REPOSITORY/DIGEST are omitted on the theory that
    # they are consumed at image pull / instance start, which never happens here.
    # v1.0.2 shipped this .conf WITHOUT the three image fields and failed at "Applied Adapter"
    # (Error: Adapter install failed) -- the first failure that was not a silent no-op, so the
    # KINDKEY discovery works and something in adapter registration rejects the pak.
    # mp_build always writes all three fields and every known-working pak carries them, so they
    # are the prime suspect. DIAGNOSTIC ONLY: this points at the vSAN pack's real public image
    # purely to satisfy the field. No adapter instance will ever exist, so nothing pulls it.
    # If this installs, the next build subtracts fields to find the minimum that still works.
    # Our own image, not a borrowed one. It is a schema-only adapter that collects nothing:
    # every figure the pack shows is computed by Operations from metrics the built-in vCenter
    # adapter already gathers. It exists because the pak installer discovers content through an
    # adapter kind, so a pak carrying dashboards, views and super metrics needs one to register.
    # Pinned by digest, as every working pak does.
    kind_conf = (f"KINDKEY={KIND_KEY}\n"
                 "API_VERSION=1.0.0\nAPI_PROTOCOL=https\nAPI_PORT=443\n"
                 f"REGISTRY={IMAGE_REGISTRY}\n"
                 f"REPOSITORY={IMAGE_REPOSITORY}\n"
                 f"DIGEST={IMAGE_DIGEST}\n")
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w", zipfile.ZIP_DEFLATED) as a:
        write_parents_first(a, [
            (f"{KIND_KEY}.conf", kind_conf),
            ("eula.txt", EULA.encode()),
            ("manifest.txt", manifest_bytes),
            ("pak_icon.png", icon),
            ("resources/resources.properties", RESOURCES.encode()),
            (f"{KIND_KEY}/conf/describe.xml", describe),
            (f"{KIND_KEY}/conf/describeSchema.xsd", open(xsd_src, "rb").read()),
            (f"{KIND_KEY}/conf/version.txt", version_txt),
            (f"{KIND_KEY}/conf/resources/resources.properties", inner_props),
            # empty image dirs, and the adapter-kind icon, as the netstats adapter.zip carries
            (f"{KIND_KEY}/conf/images/TraversalSpec/", None),
            (f"{KIND_KEY}/conf/images/ResourceKind/", None),
            (f"{KIND_KEY}/conf/images/AdapterKind/{KIND_KEY}.png", icon),
        ])

    members = {
        "manifest.txt": manifest_bytes,
        "eula.txt": EULA.encode(),
        "pak_icon.png": icon,
        "resources/resources.properties": RESOURCES.encode(),
        f"content/dashboards/{DASH_DIR}/{DASH_DIR}.json": json.dumps(dash, indent=1).encode(),
        f"content/dashboards/{REFRESH_DIR}/{REFRESH_DIR}.json": json.dumps(refresh, indent=1).encode(),
        f"content/dashboards/{MTAT_DIR}/{MTAT_DIR}.json": json.dumps(mtat, indent=1).encode(),
        **{f"content/customgroups/{f}": open(os.path.join(BUILD, "customgroups", f), "rb").read()
           for f in sorted(os.listdir(os.path.join(BUILD, "customgroups")))},
        # one file per super metric, each a single-entry {uuid: definition} map -- the shape
        # the vCommunity pack (SDK-built, 37 super metrics, vcops_minimum_version 8.18.0) ships
        **{f"content/supermetrics/{v['name'].replace('|', ' ').replace('/', ' ')}.json":
           json.dumps({k: v}, indent=1).encode() for k, v in sms.items()},
        "adapter.zip": inner.getvalue(),
        # Views live under content/reports/, NOT a views/ directory, and their GUIDs travel in
        # the XML -- which is why a shipped dashboard can hard-code viewDefinitionId and have it
        # resolve on every install (LESSONS.md 3.3, 3.5).
        **{f"content/reports/{d}/{f}": open(os.path.join(BUILD, "reports", d, f), "rb").read()
           for d in sorted(os.listdir(os.path.join(BUILD, "reports")))
           if os.path.isdir(os.path.join(BUILD, "reports", d))
           for f in os.listdir(os.path.join(BUILD, "reports", d))},
        # scaffold schema files every SDK-built pak ships under content/; inert but present
        "content/alertdefs/alertDefinitionSchema.xsd": open(os.path.join(HERE, "alertDefinitionSchema.xsd"), "rb").read(),
        "content/traversalspecs/traversalSpecsSchema.xsd": open(os.path.join(HERE, "traversalSpecsSchema.xsd"), "rb").read(),
    }

    # self-checks before anything is written
    problems = []
    json.loads(members["manifest.txt"])
    if MANIFEST["adapter_kinds"] != [KIND_KEY]:
        problems.append("manifest adapter_kinds must name the schema-only kind")
    for name, data in members.items():
        if name.endswith((".json", ".txt", ".properties")):
            hit = NAME_AUDIT.search(data.decode())
            if hit:
                problems.append(f"{name}: instance name / domain / IP found: {hit.group(0)!r}")
    # The three shapes that installed with a clean log and registered nothing (LESSONS 4.12):
    # no adapter.zip; adapter.zip without describe.xml; describe.xml without <Kind>.conf.
    # Mirrors netstats' verify_pak.py check 9. A clean install log proves nothing.
    inner_names = set(zipfile.ZipFile(io.BytesIO(members["adapter.zip"])).namelist())
    if "adapter.zip" not in MANIFEST["adapters"]:
        problems.append("manifest.adapters must list adapter.zip")
    conf_name = f"{KIND_KEY}.conf"
    if conf_name not in inner_names:
        problems.append(f"adapter.zip lacks {conf_name}: the installer discovers the adapter from it")
    elif f"KINDKEY={KIND_KEY}" not in kind_conf:
        problems.append(f"{conf_name} KINDKEY must equal the manifest adapter kind {KIND_KEY}")
    if f"{KIND_KEY}/conf/describe.xml" not in inner_names:
        problems.append(f"adapter.zip lacks {KIND_KEY}/conf/describe.xml")
    img = [f for f in ("REGISTRY=", "REPOSITORY=", "DIGEST=") if f in kind_conf]
    if img and len(img) != 3:
        problems.append(f"image fields must be all present or all absent, got {img}")
    # no dangling view references: every viewDefinitionId the dashboard names must be defined
    # by a view the pak actually ships
    import re as _re
    shipped_guids = set()
    for name, data in list(members.items()):
        if name.startswith("content/reports/") and name.endswith(".xml"):
            shipped_guids |= set(_re.findall(r'<ViewDef id="([^"]+)"', data.decode()))
    named = set(_re.findall(r'"viewDefinitionId": "([^"]+)"', json.dumps(dash) + json.dumps(refresh)
                                + json.dumps(mtat)))
    if named - shipped_guids:
        problems.append(f"dashboard names view GUIDs the pak does not ship: {sorted(named - shipped_guids)}")
    if shipped_guids - named:
        problems.append(f"pak ships views nothing references: {sorted(shipped_guids - named)}")
    # A super metric name containing '|' or ':' is read by the importer, creates nothing, and
    # reports imported=0 with no error. Measured 2026-10-16: 18 of 18 failed exactly that way.
    for v in sms.values():
        if "|" in v["name"] or ":" in v["name"]:
            problems.append(f"super metric name may not contain '|' or ':': {v['name']!r} "
                            f"-- the importer would silently create nothing")
    refs = {f"Super Metric|sm_{k}" for k in sms}
    used = set(re.findall(r"Super Metric\|sm_[0-9a-f-]+",
                          json.dumps(dash) + json.dumps(refresh) + json.dumps(mtat)))
    if used - refs:
        problems.append(f"dashboard references super metrics not in the pak: {sorted(used - refs)}")
    if problems:
        for p in problems:
            print("SELF-CHECK FAILED:", p, file=sys.stderr)
        return 1

    # Directory entries, and the full set of content subdirectories an SDK-built pak carries
    # even when empty. Matched against iSDK_VsanHostMetrics 1.4.6, which is installed and
    # running on the lab instance -- the only pak structure here proven to survive an install.
    # The empty ones are inert scaffolding, but shipping the same shape as a pak known to
    # install removes a variable from the first attempt rather than betting on it.
    dirs = [
        "content/", "content/alertdefs/", "content/customgroups/", "content/dashboards/",
        "content/files/", "content/files/reskndmetric/", "content/files/solutionconfig/",
        "content/files/topowidget/", "content/files/txtwidget/", "content/policies/",
        "content/recommendations/", "content/reports/", "content/resources/",
        "content/supermetrics/", "content/symptomdefs/", "content/traversalspecs/",
        "resources/",
    ]
    # Dashboards and reports each live in their own subdirectory. Derive those from the members
    # so a new dashboard cannot ship without its directory entry.
    for name in sorted(members):
        parts = name.split("/")
        if len(parts) == 4 and parts[0] == "content":
            d = f"{parts[0]}/{parts[1]}/{parts[2]}/"
            if d not in dirs:
                dirs.append(d)

    out = os.path.join(BUILD, f"{PAK_NAME}_{VERSION}.pak")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        write_parents_first(z, list(members.items()) + [(d, None) for d in dirs],
                            last=("adapter.zip",))
    for label, blob in (("pak", open(out, "rb").read()), ("adapter.zip", members["adapter.zip"])):
        bad = children_before_parents(blob)
        if bad:
            print(f"SELF-CHECK FAILED: {label} stores files before their directory entries: "
                  f"{bad[:5]}. The installer extracts in stored order and creates a directory "
                  f"only at its own entry, so this aborts with NoSuchFileException "
                  f"(2.1.0, 2026-10-21).", file=sys.stderr)
            return 1
    print(f"wrote {out}  ({os.path.getsize(out)} bytes)")
    for name, data in members.items():
        print(f"   {len(data):>7}  {name}")
    print(f"self-check passed: adapter.zip carries {KIND_KEY}.conf + describe.xml, no instance names, "
          f"{len(sms)} super metrics, dashboard references resolve")
    return 0


if __name__ == "__main__":
    sys.exit(main())
