FROM base-adapter:python-1.2.0
LABEL org.opencontainers.image.source="https://github.com/nickfirefoot/memorytieradvancedmonitoring" \
      org.opencontainers.image.description="Collects the memory-tiering disqualifiers VCF Operations cannot otherwise see: 1GB pages, large-page overrides, locked reservations, latency sensitivity, PCI passthrough and vGPU, NUMA node affinity." \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.title="Memory Tier Advanced"
COPY commands.cfg .
COPY adapter_requirements.txt .
RUN pip3 install -r adapter_requirements.txt --upgrade
COPY app app
