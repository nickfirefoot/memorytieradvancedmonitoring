#!/usr/bin/env python3
"""Memory Tier Advanced — collects the tiering disqualifiers Operations cannot otherwise see.

WHY THIS COLLECTS ANYTHING AT ALL
---------------------------------
A VM cannot be memory-tiered if its memory is pinned to DRAM. The built-in vCenter adapter
exposes three `extraConfig` keys out of 208 VM properties, and none of the ones that matter, so
a dashboard built on it alone will show a vGPU host full of fully-pinned VMs as a perfect
tiering candidate. An adapter can read these and publish them as properties; the vCommunity
pack does the same thing through a configurable list. Our list is short and fixed, so it is
written down here rather than read from a file on the appliance.

These settings are CONFIGURATION, not telemetry: they change when someone edits a VM, not every
five minutes. Collection is therefore a property pull, cheap, and carries no time series.

WHAT IT PUBLISHES, AND WHERE
----------------------------
Two object kinds, each attached as a CHILD of the vCenter adapter's own object, so a super
metric can roll up from the cluster without caring which adapter produced the data:

    MemTierAdvancedVM    child of VMWARE VirtualMachine
    MemTierAdvancedHost  child of VMWARE HostSystem

Attaching rather than adding properties to the vCenter adapter's objects directly is
deliberate. Matching another adapter's object identity and pushing properties into it risks
overwriting what that adapter owns -- the vSAN pack renamed every host in this lab by supplying
the wrong name alongside a matching key. A child object cannot do that.

THE NAME ON A PARENT IS AUTHORITATIVE. `_vc_parent` supplies the object's real vCenter name; any
other value RENAMES the object for every consumer of that vCenter. If a name cannot be resolved
the relationship is skipped rather than guessed.

ONE LIMITATION, INHERITED FROM THE PLATFORM
-------------------------------------------
"Once collected, a property stays with the object forever. You cannot delete it, unless the
object itself is deleted." So the key list below is deliberate and short; it is not a place to
experiment against a live instance.
"""
import ssl
import sys

import aria.ops.adapter_logging as logging
from aria.ops.adapter_instance import AdapterInstance
from aria.ops.definition.adapter_definition import AdapterDefinition
from aria.ops.object import Identifier, Key, Object
from aria.ops.result import CollectResult, EndpointResult, TestResult
from aria.ops.timer import Timer

logger = logging.getLogger(__name__)

ADAPTER_KIND = "MemTierAdvanced"
ADAPTER_NAME = "Memory Tier Advanced"
VM_KIND = "MemTierAdvancedVM"
HOST_KIND = "MemTierAdvancedHost"

VC_ADAPTER = "VMWARE"
VC_VM, VC_HOST = "VirtualMachine", "HostSystem"

HOST_ID, USER_ID, VERIFY_ID = "vcenter_host", "vcenter_user", "verify_certs"
CRED_KIND, PASSWORD_ID = "memtier_vc_credential", "vcenter_password"

# VM extraConfig keys that pin memory. Fixed list, deliberately short -- a property, once
# collected, can never be removed from an object.
VM_EXTRA = {
    "sched.mem.lpage.enable1GPage": "lpage1GB",
    "sched.mem.lpage.enableLPage": "lpageEnabled",
    "monitor_control.disable_mmu_largepages": "mmuLargePagesDisabled",
}
# ESXi advanced settings governing large-page backing.
HOST_ADVANCED = ["Mem.AllocGuestLargePage", "LPage.LPageAlwaysTryForNPT",
                 "LPage.LPageDefragEnable", "LPage.MaxSharedPages"]


def adapter_definition() -> AdapterDefinition:
    d = AdapterDefinition(ADAPTER_KIND, ADAPTER_NAME)
    d.define_string_parameter(HOST_ID, "vCenter Server",
                              description="FQDN of the vCenter Server. An IP works only with "
                                          "certificate verification off.")
    d.define_string_parameter(USER_ID, "vCenter username",
                              description="Must include the domain, e.g. user@vsphere.local. "
                                          "READ-ONLY is sufficient: this adapter only reads "
                                          "configuration and never writes.")
    d.define_enum_parameter(VERIFY_ID, "Verify vCenter certificate",
                            values=["true", "false"], default="false")
    cred = d.define_credential_type(CRED_KIND, "vCenter credential")
    cred.define_password_parameter(PASSWORD_ID, "vCenter password", required=True)

    vm = d.define_object_type(VM_KIND, "Memory Tier VM Configuration")
    vm.define_string_identifier("vm_moref", "VM MoRef")
    vm.define_string_identifier("vc_uuid", "vCenter UUID")
    for label in ("lpage1GB", "lpageEnabled", "mmuLargePagesDisabled",
                  "latencySensitivity", "memoryReservationLockedToMax",
                  "passthroughDevices", "numaNodeAffinity"):
        vm.define_string_property(label, label)
    # Numeric so a cluster rollup can SUM it: "how many VMs here cannot be tiered".
    vm.define_metric("pinned", "Pinned to DRAM (1 = cannot be tiered)")
    vm.define_metric("pinnedMemoryKB", "Memory pinned to DRAM (KB)")

    host = d.define_object_type(HOST_KIND, "Memory Tier Host Configuration")
    host.define_string_identifier("host_moref", "Host MoRef")
    host.define_string_identifier("vc_uuid", "vCenter UUID")
    for label in HOST_ADVANCED:
        host.define_string_property(label.replace(".", "_"), label)
    return d


def _connect(adapter_instance):
    from pyVim.connect import SmartConnect
    host = adapter_instance.get_identifier_value(HOST_ID)
    user = adapter_instance.get_identifier_value(USER_ID)
    pwd = adapter_instance.get_credential_value(PASSWORD_ID)
    verify = str(adapter_instance.get_identifier_value(VERIFY_ID)).lower() == "true"
    ctx = ssl.create_default_context()
    if not verify:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return SmartConnect(host=host, user=user, pwd=pwd, sslContext=ctx)


def _vc_parent(cache, kind, moref, vc_uuid, name):
    """An Object keyed exactly as the vCenter adapter keys its own, so Operations matches the
    existing object rather than creating a second one. Only the two uniqueness identifiers are
    set; adding non-unique ones risks a mismatch when they change.

    `name` must be the object's REAL vCenter name. Supplying anything else renames it for every
    consumer of that vCenter."""
    if not (moref and vc_uuid and name):
        return None
    ckey = (kind, moref)
    if ckey not in cache:
        cache[ckey] = Object(Key(
            adapter_kind=VC_ADAPTER, object_kind=kind, name=name,
            identifiers=[Identifier("VMEntityObjectID", moref),
                         Identifier("VMEntityVCID", vc_uuid)]))
    return cache[ckey]


def _vm_config(vm):
    """Every disqualifier for one VM, read from config. Returns (props, pinned, pinned_kb)."""
    cfg = vm.config
    props = {}
    extra = {o.key: str(o.value) for o in (cfg.extraConfig or [])}
    for key, label in VM_EXTRA.items():
        props[label] = extra.get(key, "not set")

    ls = getattr(cfg, "latencySensitivity", None)
    props["latencySensitivity"] = str(getattr(ls, "level", "normal") or "normal")
    locked = bool(getattr(cfg, "memoryReservationLockedToMax", False))
    props["memoryReservationLockedToMax"] = str(locked).lower()

    # PCI passthrough and vGPU both force a 100% memory reservation.
    passthru = []
    for dev in (cfg.hardware.device or []):
        cls = type(dev).__name__
        if "PciPassthrough" in cls or "PCIPassthrough" in cls:
            backing = type(dev.backing).__name__ if getattr(dev, "backing", None) else ""
            passthru.append("vGPU" if "Vmiop" in backing else "PCI")
    props["passthroughDevices"] = ",".join(passthru) if passthru else "none"

    numa = [f"{o.key}={o.value}" for o in (cfg.extraConfig or [])
            if o.key.startswith("numa.nodeAffinity")]
    props["numaNodeAffinity"] = ";".join(numa) if numa else "none"

    mem_kb = (cfg.hardware.memoryMB or 0) * 1024
    reservation_mb = getattr(cfg.memoryAllocation, "reservation", 0) or 0
    fully_reserved = mem_kb > 0 and reservation_mb * 1024 >= mem_kb

    pinned = any([
        props["lpage1GB"].upper() in ("TRUE", "1"),
        props["latencySensitivity"].lower() == "high",
        locked,
        bool(passthru),
        fully_reserved,
    ])
    return props, (1 if pinned else 0), (mem_kb if pinned else 0)


def test(adapter_instance: AdapterInstance) -> TestResult:
    result = TestResult()
    si = None
    try:
        from pyVim.connect import Disconnect
        si = _connect(adapter_instance)
        about = si.RetrieveContent().about
        logger.info("connected to %s %s", about.fullName, about.instanceUuid)
    except Exception as e:
        logger.exception("test failed")
        result.with_error(f"Could not connect to vCenter: {e}")
    finally:
        if si:
            try:
                Disconnect(si)
            except Exception:
                pass
    return result


def collect(adapter_instance: AdapterInstance) -> CollectResult:
    from pyVim.connect import Disconnect
    from pyVmomi import vim
    with Timer(logger, "Collection"):
        result = CollectResult()
        si = None
        try:
            si = _connect(adapter_instance)
            content = si.RetrieveContent()
            vc_uuid = content.about.instanceUuid
            parents: dict = {}
            n_vm = n_host = n_pinned = 0

            view = content.viewManager.CreateContainerView(
                content.rootFolder, [vim.VirtualMachine], True)
            vms = list(view.view)
            view.Destroy()
            for vm in vms:
                try:
                    if vm.runtime.powerState != "poweredOn" or vm.config is None:
                        continue
                    props, pinned, pinned_kb = _vm_config(vm)
                except Exception as e:
                    # Loud, not silent. A dropped sample is how a defect survives a green run.
                    logger.warning("skipping VM %s: %s", getattr(vm, "name", "?"), e)
                    continue
                obj = result.object(ADAPTER_KIND, VM_KIND, vm.name,
                                    identifiers=[Identifier("vm_moref", vm._moId),
                                                 Identifier("vc_uuid", vc_uuid)])
                for k, v in props.items():
                    obj.with_property(k, v)
                obj.with_metric("pinned", pinned)
                obj.with_metric("pinnedMemoryKB", pinned_kb)
                n_vm += 1
                n_pinned += pinned
                parent = _vc_parent(parents, VC_VM, vm._moId, vc_uuid, vm.name)
                if parent is not None:
                    parent.add_child(obj)

            view = content.viewManager.CreateContainerView(
                content.rootFolder, [vim.HostSystem], True)
            hosts = list(view.view)
            view.Destroy()
            for host in hosts:
                try:
                    opts = host.configManager.advancedOption.QueryOptions()
                    wanted = {o.key: str(o.value) for o in opts if o.key in HOST_ADVANCED}
                except Exception as e:
                    logger.warning("skipping host %s: %s", getattr(host, "name", "?"), e)
                    continue
                obj = result.object(ADAPTER_KIND, HOST_KIND, host.name,
                                    identifiers=[Identifier("host_moref", host._moId),
                                                 Identifier("vc_uuid", vc_uuid)])
                for key in HOST_ADVANCED:
                    obj.with_property(key.replace(".", "_"), wanted.get(key, "not set"))
                n_host += 1
                parent = _vc_parent(parents, VC_HOST, host._moId, vc_uuid, host.name)
                if parent is not None:
                    parent.add_child(obj)

            for parent in parents.values():
                result.add_object(parent)
            logger.info("collected %d VMs (%d pinned) and %d hosts, linked to %d vCenter objects",
                        n_vm, n_pinned, n_host, len(parents))
            if n_vm == 0 and vms:
                # An empty successful collection is the failure mode that hides everything else.
                result.with_error("Connected, but produced no VM objects")
        except Exception as e:
            logger.exception("collection failed")
            result.with_error(f"Collection failed: {e}")
        finally:
            if si:
                try:
                    Disconnect(si)
                except Exception:
                    pass
        return result


def get_endpoints(adapter_instance: AdapterInstance) -> EndpointResult:
    result = EndpointResult()
    host = adapter_instance.get_identifier_value(HOST_ID)
    if host:
        result.with_endpoint(host)
    return result


def main(argv):
    logging.setup_logging("adapter.log")
    cmd = argv[0] if argv else ""
    if cmd == "adapter_definition":
        adapter_definition().send_results()
    elif cmd == "test":
        test(AdapterInstance.from_input()).send_results()
    elif cmd == "collect":
        collect(AdapterInstance.from_input()).send_results()
    elif cmd == "endpoint_urls":
        get_endpoints(AdapterInstance.from_input()).send_results()
    else:
        logger.error("unknown command %r", cmd)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
