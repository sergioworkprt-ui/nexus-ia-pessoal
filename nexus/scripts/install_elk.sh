#!/usr/bin/env bash
# NEXUS ELK Stack Installer — Elasticsearch 8 + Logstash + Kibana
# Target: Ubuntu 22.04 LTS | Run as root: sudo bash install_elk.sh
set -euo pipefail

log()  { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] [ELK-INSTALL] $*"; }
fail() { log "FAILED: $*"; exit 1; }

[ "$(id -u)" = "0" ] || fail "Run as root: sudo bash install_elk.sh"

NEXUS_HOME="${NEXUS_HOME:-/opt/nexus}"
ELK_HEAP="${ELK_HEAP:-512m}"

log "=== NEXUS ELK Stack Installation ==="
log "NEXUS_HOME=$NEXUS_HOME  ELK_HEAP=$ELK_HEAP"

# ── 1. System dependencies ────────────────────────────────────────────────────────────
log "Installing system dependencies..."
apt-get update -qq
apt-get install -y -qq \
    openjdk-21-jre-headless \
    apt-transport-https \
    curl gnupg ca-certificates \
    2>/dev/null

# ── 2. Elastic APT repository ───────────────────────────────────────────────────────────
log "Adding Elastic APT repository..."
curl -fsSL https://artifacts.elastic.co/GPG-KEY-elasticsearch 2>/dev/null | \
    gpg --dearmor -o /usr/share/keyrings/elastic-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/elastic-keyring.gpg] https://artifacts.elastic.co/packages/8.x/apt stable main" \
    > /etc/apt/sources.list.d/elastic-8.x.list
apt-get update -qq

# ── 3. Install Elasticsearch ────────────────────────────────────────────────────────────
log "Installing Elasticsearch..."
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq elasticsearch

cat > /etc/elasticsearch/elasticsearch.yml << 'ES_CONF'
cluster.name: nexus-elk
node.name: nexus-node-1
network.host: 127.0.0.1
http.port: 9200
discovery.type: single-node
xpack.security.enabled: false
xpack.security.http.ssl.enabled: false
xpack.security.transport.ssl.enabled: false
ES_CONF

# Limit heap for small VPS (override ELK_HEAP env var)
mkdir -p /etc/elasticsearch/jvm.options.d
cat > /etc/elasticsearch/jvm.options.d/nexus-heap.options << HEAP_CONF
-Xms${ELK_HEAP}
-Xmx${ELK_HEAP}
HEAP_CONF

systemctl daemon-reload
systemctl enable elasticsearch
systemctl restart elasticsearch
log "Elasticsearch started (heap: $ELK_HEAP)"

# ── 4. Install Logstash ────────────────────────────────────────────────────────────────────
log "Installing Logstash..."
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq logstash

# NEXUS pipeline: reads all .log files, parses JSON and plain, ships to ES
mkdir -p /etc/logstash/conf.d
cat > /etc/logstash/conf.d/nexus.conf << LOGSTASH_CONF
input {
  file {
    path => "${NEXUS_HOME}/logs/*.log"
    start_position => "beginning"
    sincedb_path => "/var/lib/logstash/nexus_sincedb"
    tags => ["nexus"]
  }
  beats {
    port => 5044
  }
}

filter {
  if [message] =~ /^\{/ {
    json {
      source => "message"
    }
    mutate {
      add_field => { "log_format" => "json" }
    }
  } else {
    grok {
      match => {
        "message" => "\\[%{TIMESTAMP_ISO8601:log_timestamp}\\] \\[%{DATA:log_module}\\] %{GREEDYDATA:log_message}"
      }
      tag_on_failure => ["_grok_failure"]
    }
    mutate {
      add_field => { "log_format" => "plain" }
    }
  }
  date {
    match => ["log_timestamp", "ISO8601"]
    target => "@timestamp"
    tag_on_failure => ["_date_failure"]
  }
}

output {
  elasticsearch {
    hosts => ["http://127.0.0.1:9200"]
    index => "nexus-logs-%{+YYYY.MM.dd}"
    action => "index"
  }
}
LOGSTASH_CONF

# Reduce Logstash heap too
sed -i 's/-Xms.*/-Xms256m/' /etc/logstash/jvm.options 2>/dev/null || true
sed -i 's/-Xmx.*/-Xmx256m/' /etc/logstash/jvm.options 2>/dev/null || true

systemctl enable logstash
systemctl restart logstash
log "Logstash started"

# ── 5. Install Kibana ─────────────────────────────────────────────────────────────────────
log "Installing Kibana..."
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq kibana

cat > /etc/kibana/kibana.yml << 'KIBANA_CONF'
server.port: 5601
server.host: "127.0.0.1"
server.name: "nexus-kibana"
elasticsearch.hosts: ["http://127.0.0.1:9200"]
logging.appenders.default.type: console
logging.root.level: warn
KIBANA_CONF

systemctl enable kibana
systemctl restart kibana
log "Kibana started"

# ── 6. Wait for Elasticsearch ───────────────────────────────────────────────────────────
log "Waiting for Elasticsearch to be ready (up to 60s)..."
for i in $(seq 1 20); do
    if curl -sf http://127.0.0.1:9200/_cluster/health > /dev/null 2>&1; then
        log "Elasticsearch ready (${i}x3s)"
        break
    fi
    sleep 3
done

# ── 7. Create NEXUS index template ──────────────────────────────────────────────────────
log "Creating NEXUS index template..."
curl -sf -X PUT http://127.0.0.1:9200/_index_template/nexus-logs \
    -H 'Content-Type: application/json' \
    -d '{
  "index_patterns": ["nexus-logs-*"],
  "template": {
    "settings": {"number_of_shards": 1, "number_of_replicas": 0},
    "mappings": {
      "properties": {
        "@timestamp":   {"type": "date"},
        "timestamp":    {"type": "date"},
        "level":        {"type": "keyword"},
        "logger":       {"type": "keyword"},
        "log_module":   {"type": "keyword"},
        "message":      {"type": "text"},
        "log_message":  {"type": "text"},
        "log_format":   {"type": "keyword"},
        "method":       {"type": "keyword"},
        "path":         {"type": "keyword"},
        "status":       {"type": "integer"},
        "duration_ms":  {"type": "float"},
        "client":       {"type": "ip"}
      }
    }
  }
}' 2>/dev/null && log "Index template created" || log "WARNING: Could not create index template (ES may still be starting)"

# ── 8. Create index lifecycle policy (30-day rotation) ─────────────────────────────────
log "Creating index lifecycle policy..."
curl -sf -X PUT http://127.0.0.1:9200/_ilm/policy/nexus-30day \
    -H 'Content-Type: application/json' \
    -d '{
  "policy": {
    "phases": {
      "hot": {"min_age": "0ms", "actions": {}},
      "delete": {"min_age": "30d", "actions": {"delete": {}}}
    }
  }
}' 2>/dev/null && log "ILM policy created" || log "WARNING: Could not create ILM policy"

# ── 9. Status summary ───────────────────────────────────────────────────────────────────
log "=== ELK Stack Installation Complete ==="
echo ""
echo "Service Status:"
for svc in elasticsearch logstash kibana; do
    STATUS=$(systemctl is-active "$svc" 2>/dev/null || echo "unknown")
    printf "  %-18s %s\n" "$svc" "$STATUS"
done
echo ""
echo "Endpoints (localhost only):"
echo "  Elasticsearch: http://127.0.0.1:9200"
echo "  Kibana:        http://127.0.0.1:5601  (startup takes ~60s)"
echo "  Logstash API:  http://127.0.0.1:9600"
echo ""
echo "Access Kibana via SSH tunnel:"
VPS_IP=$(hostname -I | awk '{print $1}')
echo "  ssh -L 5601:127.0.0.1:5601 user@${VPS_IP}"
echo "  Then open: http://localhost:5601"
echo ""
echo "NEXUS logs will be indexed into: nexus-logs-YYYY.MM.DD"
echo "Configure Kibana data view: Menu → Discover → Create data view → nexus-logs-*"
