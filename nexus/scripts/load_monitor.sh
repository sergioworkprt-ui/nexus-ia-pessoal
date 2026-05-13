#!/usr/bin/env bash
# Load monitor: CPU/RAM/disk monitoring with recommendations and JSONL history
set -euo pipefail

NEXUS_HOME="${NEXUS_HOME:-/opt/nexus}"
LOAD_HISTORY="$NEXUS_HOME/monitor/load_history.jsonl"
REPORT_FILE="$NEXUS_HOME/monitor/load_report.md"
MAX_ENTRIES=50

mkdir -p "$NEXUS_HOME/monitor"

TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

JSON=$(python3 << 'PYEOF'
import os, json, psutil, datetime

cpu = psutil.cpu_percent(interval=1)
cpu_cores = psutil.cpu_count() or 1
mem = psutil.virtual_memory()
disk = psutil.disk_usage("/")
load_avg = os.getloadavg()

procs = []
for p in sorted(
    psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']),
    key=lambda p: p.info.get('cpu_percent') or 0,
    reverse=True
)[:5]:
    procs.append({
        "pid": p.info['pid'],
        "name": p.info['name'],
        "cpu_pct": round(p.info.get('cpu_percent') or 0, 1),
        "mem_pct": round(p.info.get('memory_percent') or 0, 1),
    })

recs = []
if cpu > 80:
    recs.append("HIGH CPU: consider scaling or optimising heavy processes")
if mem.percent > 85:
    recs.append("HIGH MEMORY: consider increasing VPS RAM or reducing in-memory caches")
if disk.percent > 85:
    recs.append("LOW DISK: clean logs/backups or expand storage")
if load_avg[0] > cpu_cores * 2:
    recs.append(f"HIGH LOAD AVG ({load_avg[0]:.1f} > {cpu_cores*2}): system overloaded")
if not recs:
    recs.append("All resources within normal range")

data = {
    "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
    "cpu": {"percent": cpu, "cores": cpu_cores, "load_avg_1m": round(load_avg[0], 2)},
    "memory": {
        "percent": mem.percent,
        "used_mb": mem.used // 1024 // 1024,
        "total_mb": mem.total // 1024 // 1024,
        "available_mb": mem.available // 1024 // 1024,
    },
    "disk": {
        "percent": disk.percent,
        "free_gb": round(disk.free / 1024**3, 2),
        "total_gb": round(disk.total / 1024**3, 2),
    },
    "top_processes": procs,
    "recommendations": recs,
}
print(json.dumps(data))
PYEOF
)

echo "$JSON" >> "$LOAD_HISTORY"
LINES=$(wc -l < "$LOAD_HISTORY")
if [ "$LINES" -gt "$MAX_ENTRIES" ]; then
    EXCESS=$((LINES - MAX_ENTRIES))
    tail -n "+$((EXCESS + 1))" "$LOAD_HISTORY" > "$LOAD_HISTORY.tmp"
    mv "$LOAD_HISTORY.tmp" "$LOAD_HISTORY"
fi

python3 - << PYEOF
import json, datetime

with open("$LOAD_HISTORY") as f:
    raw_lines = [l.strip() for l in f if l.strip()]

entries = [json.loads(l) for l in raw_lines[-10:]]
latest = entries[-1] if entries else {}

out = [
    "# NEXUS Load Report",
    f"Generated: {datetime.datetime.utcnow().isoformat()}Z",
    "",
    "## Latest Snapshot",
    f"- CPU: {latest.get('cpu',{}).get('percent','?')}%",
    f"- Memory: {latest.get('memory',{}).get('percent','?')}%",
    f"- Disk: {latest.get('disk',{}).get('percent','?')}%",
    "",
    "## Recommendations",
]
for r in latest.get("recommendations", []):
    out.append(f"- {r}")

out += [
    "",
    "## History (last 10 snapshots)",
    "| Time | CPU% | MEM% | DISK% |",
    "|------|------|------|-------|",
]
for e in entries:
    t = e.get("timestamp", "?")[:19]
    c = e.get("cpu", {}).get("percent", "?")
    m = e.get("memory", {}).get("percent", "?")
    d = e.get("disk", {}).get("percent", "?")
    out.append(f"| {t} | {c} | {m} | {d} |")

with open("$REPORT_FILE", "w") as f:
    f.write("\n".join(out) + "\n")
PYEOF

echo "Load monitor done: $TIMESTAMP"
cat "$REPORT_FILE"
