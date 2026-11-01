#!/usr/bin/env bash
# Legt das private Repo an (falls nicht vorhanden) und pusht. Token kommt aus ~/.hermes/.env.
set -u
cd /home/speedy/Dokumente/dev/DocPipeline || exit 1
NAME="DocPipeline"
TOKEN=$(grep -m1 '^GITHUB_TOKEN=' "$HOME/.hermes/.env" | cut -d= -f2- | tr -d '"'"'"'\r')
if [ -z "$TOKEN" ]; then echo "FEHLER: kein GITHUB_TOKEN gefunden"; exit 1; fi

CODE=$(curl -s -o /tmp/repo_create.json -w '%{http_code}' -X POST https://api.github.com/user/repos \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Accept: application/vnd.github+json' \
  -H 'X-GitHub-Api-Version: 2022-11-28' \
  -d "{\"name\":\"$NAME\",\"private\":true,\"description\":\"Schema-driven document field extraction: OCR, chunking, GLiNER2, dedup; CLI and FastAPI\",\"has_issues\":true,\"has_wiki\":false}")
echo "Repo-Anlage HTTP $CODE"
python3 - <<'PY'
import json
try:
    d = json.load(open('/tmp/repo_create.json'))
except Exception:
    raise SystemExit
print("full_name:", d.get("full_name"))
print("private:", d.get("private"))
print("url:", d.get("html_url"))
print("ssh:", d.get("ssh_url"))
if d.get("errors"):
    print("errors:", d["errors"])
PY

git remote remove origin 2>/dev/null
git remote add origin "git@github.com:FBR65/$NAME.git"
git push -u origin master 2>&1 | tail -8
echo "== remote"; git remote -v
echo "== log"; git log --oneline -2
