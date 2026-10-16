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
import os
import re
import struct
import sys
import zipfile
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
BUILD = os.path.join(HERE, "build")

VERSION = "1.4.1"
IMAGE_REGISTRY = "ghcr.io"
IMAGE_REPOSITORY = "/nickfirefoot/memorytieradvancedmonitoring"
IMAGE_DIGEST = "sha256:156894ed43475c4281938f23cb4511ea04db6c7599cfce1f53f61b901e458103"      # 1.4.0: finding C -- allocated split by power state
PAK_NAME = "MemoryTieringSizing"           # manifest "name"; also injected as adapterName
KIND_KEY = "MemTierSizing"                 # schema-only adapter kind: declared so content imports, never instantiated
DISPLAY_NAME = "Memory Tiering Sizing"
VENDOR = "Nick Wilson"
DESCRIPTION = ("Sizes a vSphere estate for VCF 9 NVMe memory tiering from metrics the vCenter "
               "adapter already collects. Content only: dashboards and super metrics, no "
               "adapter, no image, no registry. Target: Operations 8.18 and later.")
DASH_DIR = "Memory_Tiering_Sizing_Clusters"   # pre-created so mp_build-style lowercasing never applies

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


def main():
    dash_src = os.path.join(BUILD, "dashboard.json")
    sm_src = os.path.join(BUILD, "supermetric.json")
    for f in (dash_src, sm_src):
        if not os.path.exists(f):
            print(f"missing {f} — run build_content.py first", file=sys.stderr)
            return 1

    dash = json.load(open(dash_src))
    # In-pak dashboards use the CONTENT-EXPORT shape, not the UI-export shape. Every dashboard
    # in the vCommunity pak (SDK-built, installed widely) carries adapterName, namePath,
    # docCenterKey, temporary, widgetInteractions, columnCount 1 and columnProportion "1-1" --
    # the exact fields the vSAN pack found absent from UI exports. Both observations are right;
    # they are two formats. The UI-import zip from build_content.py stays in the UI shape.
    for d in dash["dashboards"]:
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
    icon = png_icon()

    # v0.3.0: content import is adapter-shaped (LESSONS.md 4.7; SDK source read by the vSAN
    # session), and describeSchema.xsd makes an AdapterKind REQUIRE at least one ResourceKind.
    # So the pak declares one schema-only adapter kind with a single adapter-instance kind
    # (type="7") that has no identifiers, no credential and no container pointer -- nothing to
    # configure, nothing that can run, exists only so the installer registers a solution and
    # reaches content/. This is how pre-SDK community content paks were distributed.
    # adapter.zip mirrors the real VsanHostMetrics pak member for member, minus <Kind>.conf.
    import io
    describe = f"""<?xml version='1.0' encoding='UTF-8'?>
<AdapterKind xmlns="http://schemas.vmware.com/vcops/schema" key="{KIND_KEY}" nameKey="1" version="1">
  <ResourceKinds>
    <ResourceKind key="{KIND_KEY}_adapter_instance" nameKey="2" type="7"/>
  </ResourceKinds>
</AdapterKind>
"""
    inner_props = f"1 = {DISPLAY_NAME}\n2 = {DISPLAY_NAME} (content only, no adapter instance needed)\n"
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
        a.writestr(f"{KIND_KEY}.conf", kind_conf)
        a.writestr("manifest.txt", manifest_bytes)
        a.writestr("eula.txt", EULA.encode())
        a.writestr("pak_icon.png", icon)
        a.writestr("resources/resources.properties", RESOURCES.encode())
        a.writestr(f"{KIND_KEY}/conf/describe.xml", describe)
        a.writestr(f"{KIND_KEY}/conf/describeSchema.xsd", open(xsd_src, "rb").read())
        a.writestr(f"{KIND_KEY}/conf/version.txt", version_txt)
        a.writestr(f"{KIND_KEY}/conf/resources/resources.properties", inner_props)
        # directory entries and empty image dirs, exactly as the real adapter.zip carries them
        for d in ("resources/", f"{KIND_KEY}/", f"{KIND_KEY}/conf/", f"{KIND_KEY}/conf/resources/",
                  f"{KIND_KEY}/conf/images/", f"{KIND_KEY}/conf/images/AdapterKind/",
                  f"{KIND_KEY}/conf/images/ResourceKind/", f"{KIND_KEY}/conf/images/TraversalSpec/"):
            a.writestr(zipfile.ZipInfo(d), b"")

    members = {
        "manifest.txt": manifest_bytes,
        "eula.txt": EULA.encode(),
        "pak_icon.png": icon,
        "resources/resources.properties": RESOURCES.encode(),
        f"content/dashboards/{DASH_DIR}/{DASH_DIR}.json": json.dumps(dash, indent=1).encode(),
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
    named = set(_re.findall(r'"viewDefinitionId": "([^"]+)"', json.dumps(dash)))
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
    used = set(re.findall(r"Super Metric\|sm_[0-9a-f-]+", json.dumps(dash)))
    if used - refs:
        problems.append(f"dashboard references super metrics not in the pak: {sorted(used - refs)}")
    if problems:
        for p in problems:
            print("SELF-CHECK FAILED:", p, file=sys.stderr)
        return 1

    out = os.path.join(BUILD, f"{PAK_NAME}_{VERSION}.pak")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in members.items():
            z.writestr(name, data)
    print(f"wrote {out}  ({os.path.getsize(out)} bytes)")
    for name, data in members.items():
        print(f"   {len(data):>7}  {name}")
    print(f"self-check passed: adapter.zip carries {KIND_KEY}.conf + describe.xml, no instance names, "
          f"{len(sms)} super metrics, dashboard references resolve")
    return 0


if __name__ == "__main__":
    sys.exit(main())
