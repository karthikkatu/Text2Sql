# SQLTexter terminal helpers. Usage:  source sqlt.sh ; sqlt_connect <db> ; sqlt_ask <db> "question"
SQLT=${SQLT:-http://127.0.0.1:5000}
SQLT_JAR=${SQLT_JAR:-/tmp/sqlt_jar.txt}
_sqlt_csrf() { curl -s -c "$SQLT_JAR" -b "$SQLT_JAR" -o /dev/null "$SQLT/version"; awk '$6=="csrf_token"{print $7}' "$SQLT_JAR"; }
_sqlt_pretty() { tr '|' '\n' | grep -v '^$\|FALKORDB' | python3 -c '
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
sqlt_connect() { curl -s -N -b "$SQLT_JAR" -H "X-CSRF-Token: $(_sqlt_csrf)" -H 'Content-Type: application/json' \
  -d "{\"url\":\"sqlite:///database/$1/$1.sqlite\"}" "$SQLT/database" | _sqlt_pretty; }
sqlt_ask() { curl -s -N -b "$SQLT_JAR" -H "X-CSRF-Token: $(_sqlt_csrf)" -H 'Content-Type: application/json' \
  -d "$(python3 -c 'import json,sys; print(json.dumps({"chat":[sys.argv[1]]}))' "$2")" "$SQLT/graphs/$1" | _sqlt_pretty; }
sqlt_list() { curl -s "$SQLT/graphs"; echo; }
