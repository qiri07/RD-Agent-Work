#!/bin/bash
echo "=== Ollama 模型下载监控 ==="
while true; do
    SIZE=$(du -sh ~/.ollama/models/ 2>/dev/null | cut -f1)
    MODELS=$(curl -s http://localhost:11434/api/tags 2>/dev/null)
    if echo "$MODELS" | grep -q "\"name\""; then
        echo "✅ 模型下载完成!"
        echo "$MODELS" | python3 -c "import sys,json; d=json.load(sys.stdin); [print(f'  - {m[\"name\"]} ({m.get(\"size\",0)//1024//1024}MB)') for m in d['models']]"
        break
    fi
    echo "[$(date '+%H:%M:%S')] 已下载: $SIZE"
    sleep 60
done
