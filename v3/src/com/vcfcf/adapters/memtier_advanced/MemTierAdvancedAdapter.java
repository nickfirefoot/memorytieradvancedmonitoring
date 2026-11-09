package com.vcfcf.adapters.memtier_advanced;

import com.vcfcf.adapter.VcfCfAdapter;
import com.vcfcf.adapter.http.ManagedHttpClient;
import com.vcfcf.adapter.spi.VcfCfCollector;
import com.vcfcf.adapter.spi.VcfCfDiscoverer;
import com.vcfcf.adapter.spi.VcfCfTester;

import com.integrien.alive.common.adapter3.AdapterBase;
import com.integrien.alive.common.adapter3.MetricData;
import com.integrien.alive.common.adapter3.ResourceKey;
import com.integrien.alive.common.adapter3.ResourceStatus;
import com.integrien.alive.common.adapter3.config.ResourceConfig;
import com.integrien.alive.common.adapter3.config.ResourceIdentifierConfig;

import java.util.List;

/**
 * Memory Tier Advanced v3 -- a deliberately minimal Tier 2 adapter.
 *
 * <p>The pak's value is its bundled content (views and a dashboard over native VMWARE metrics,
 * validated on Aria Operations 8.18.7). This adapter exists because a pak carries one, and because
 * every pack is a Java pak from v3 on. It has no target system: no credentials, no outbound
 * connection, and it never writes to an object of another adapter kind. It registers one World (the
 * traversal anchor every factory pak registers) and collects nothing.
 *
 * <p>Framework idioms kept from the VCF Content Factory template: keyed constructors (so the default
 * onDescribe resolves describe.xml), and discovery driven from the collect path, because VCF
 * Operations 9.0.2+ never calls onDiscover for adapter3 collectors.
 */
public final class MemTierAdvancedAdapter extends VcfCfAdapter<MemTierAdvancedAdapter.Config> {

    /** MUST match the AdapterKind key in describe.xml and adapter_kind in adapter.yaml. */
    private static final String ADAPTER_KIND = "memtier_advanced";
    private static final String WORLD_KIND = "World";
    private static final String WORLD_NAME = "Memory Tier Advanced World";

    /** Nothing to configure: the instance has no connection settings. */
    public static final class Config {
    }

    public MemTierAdvancedAdapter() {
        super(ADAPTER_KIND);
    }

    public MemTierAdvancedAdapter(String adapterDir, Integer adapterInstanceId) {
        super(ADAPTER_KIND, adapterDir, adapterInstanceId);
    }

    @Override
    protected void configureAdapter(ResourceStatus status, ResourceConfig rc) {
        this.config = new Config();
        logInfo("MemTierAdvancedAdapter configured: content-only pak, no target system");
    }

    /** Test Connection: there is no system to reach, so it passes and says why. */
    @Override
    protected VcfCfTester<Config> getTester() {
        return (cfg, http, param) ->
                logInfo("Test OK: Memory Tier Advanced has no target system to connect to");
    }

    /** Kept for any platform that does call onDiscover; same enumeration as the collect path. */
    @Override
    protected VcfCfDiscoverer<Config> getDiscoverer() {
        return (cfg, http, param, dr) -> dr.addResource(world());
    }

    @Override
    protected VcfCfCollector<Config> getCollector() {
        return new VcfCfCollector<Config>() {
            @Override
            public boolean needsRediscovery(Config cfg) {
                return true;
            }

            @Override
            public void rediscover(Config cfg, ManagedHttpClient http,
                    ResourceConfig adapterInst, AdapterBase adapter)
                    throws InterruptedException, Exception {
                if (isAbortRequested()) return;
                registerNewResource(world());
            }

            @Override
            public void collect(Config cfg, ManagedHttpClient http, ResourceConfig rc,
                    List<MetricData> out, AdapterBase adapter)
                    throws InterruptedException, Exception {
                // World is a traversal anchor: keepalive only, no metrics. Nothing else is ours.
            }
        };
    }

    private ResourceConfig world() {
        ResourceKey key = new ResourceKey(WORLD_NAME, WORLD_KIND, ADAPTER_KIND);
        key.addIdentifier(new ResourceIdentifierConfig("world_id", "memtier_advanced_world", true));
        return new ResourceConfig(key);
    }
}
