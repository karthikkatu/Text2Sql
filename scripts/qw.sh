# QueryWeaver terminal helpers. Usage:  source qw.sh ; qw_connect <db> ; qw_ask <db> "question"
QW=${QW:-http://127.0.0.1:5000}
QW_JAR=${QW_JAR:-/tmp/qw_jar.txt}
_qw_csrf() { curl -s -c "$QW_JAR" -b "$QW_JAR" -o /dev/null "$QW/version"; awk '$6=="csrf_token"{print $7}' "$QW_JAR"; }
_qw_pretty() { tr '|' '\n' | grep -v '^$\|FALKORDB' | python3 -c '
import sys, json
for line in sys.stdin:
    try: e = json.loads(line)
    except Exception: continue
    t = e.get("type")
    if t == "sql_query": print("SQL    :", e["data"])
    elif t == "query_result": print("ROWS   :", json.dumps(e["data"])[:600])
    elif t == "ai_response": print("ANSWER :", e["message"].replace("\n", " ")[:400])
    elif t in ("followup_questions", "error", "destructive_confirmation"): print(t.upper() + ":", e.get("message"))
    elif t == "reasoning_step": print("  ·", e["message"])
'; }
qw_connect() { curl -s -N -b "$QW_JAR" -H "X-CSRF-Token: $(_qw_csrf)" -H 'Content-Type: application/json' \
  -d "{\"url\":\"sqlite:///database/$1/$1.sqlite\"}" "$QW/database" | _qw_pretty; }
qw_ask() { curl -s -N -b "$QW_JAR" -H "X-CSRF-Token: $(_qw_csrf)" -H 'Content-Type: application/json' \
  -d "$(python3 -c 'import json,sys; print(json.dumps({"chat":[sys.argv[1]]}))' "$2")" "$QW/graphs/$1" | _qw_pretty; }
qw_list() { curl -s "$QW/graphs"; echo; }
