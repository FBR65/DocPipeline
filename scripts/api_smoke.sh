#!/usr/bin/env bash
# Echt-Test der API gegen den laufenden Server (kein Testdoppel).
set -u
cd /home/speedy/Dokumente/dev/DocPipeline || exit 1
export DOCPIPELINE_SCHEMA_FILE=data/schema.invoice.toml
export DOCPIPELINE_BASE_DIR=/tmp/dp_api
mkdir -p /tmp/dp_api
cp -f /home/speedy/.hermes/cache/scratch/page-1.png /tmp/dp_api/seite1.png

uv run docpipeline serve --host 127.0.0.1 --port 8765 >/tmp/dp_api/server.log 2>&1 &
SERVER=$!
for i in $(seq 1 40); do
  sleep 1
  if curl -sf -m 2 http://127.0.0.1:8765/v1/health >/tmp/dp_api/health.json; then break; fi
done

echo "== health"; cat /tmp/dp_api/health.json; echo
echo "== schema"; curl -s -m 5 http://127.0.0.1:8765/v1/schema; echo
echo "== openapi"; curl -s -o /dev/null -w "%{http_code}\n" -m 5 http://127.0.0.1:8765/v1/openapi.json
echo "== extract als Pfad"; curl -s -m 300 -X POST http://127.0.0.1:8765/v1/extract \
  -H 'Content-Type: application/json' -d '{"path": "/tmp/dp_api/seite1.png"}' | head -c 700; echo
echo "== extract als Upload"; curl -s -m 300 -X POST http://127.0.0.1:8765/v1/extract \
  -F "file=@/tmp/dp_api/seite1.png" | python3 -c 'import json,sys; d=json.load(sys.stdin); print("source:", d["source"], "| pages:", d["pages"], "| ocr_pages:", d["ocr"]["pages_ocr"], "| entities:", len(d["entities"])); [print("  ", e["label"], "=", e["text"], round(e["score"],3)) for e in d["entities"][:8]]'
echo "== export"; curl -s -m 300 -X POST http://127.0.0.1:8765/v1/export \
  -H 'Content-Type: application/json' -d '{"path": "/tmp/dp_api/seite1.png"}' | head -c 400; echo
echo "== pfad ausserhalb der basis"; curl -s -o /dev/null -w "%{http_code}\n" -m 10 -X POST \
  http://127.0.0.1:8765/v1/extract -H 'Content-Type: application/json' -d '{"path": "/etc/hostname"}'
echo "== ungueltige endung"; printf 'hallo' > /tmp/dp_api/notiz.txt
curl -s -o /dev/null -w "%{http_code}\n" -m 20 -X POST http://127.0.0.1:8765/v1/extract \
  -F "file=@/tmp/dp_api/notiz.txt"

kill $SERVER 2>/dev/null
wait $SERVER 2>/dev/null
echo "== server beendet"
