#!/bin/bash
cd /run/media/onai/MyDisk/Work/RD-Agent-Work
source rdagent-env/bin/activate

echo "=== RD-Agent 环境测试 ==="
echo ""

# Test LLM
echo "1. 测试 LLM..."
python -c "
import litellm
try:
    response = litellm.completion(
        model='ollama/qwen2:0.5b',
        messages=[{'role': 'user', 'content': 'Reply with: OK'}],
        max_tokens=10,
        api_base='http://localhost:11434/v1'
    )
    print('✅ LLM 测试成功!')
    print('   Response:', response.choices[0].message.content)
except Exception as e:
    print(f'❌ LLM 测试失败: {e}')
"

echo ""
echo "2. 测试 Docker..."
docker info >/dev/null 2>&1 && echo "✅ Docker 正常" || echo "❌ Docker 权限不足 (需 sudo chmod 666 /var/run/docker.sock)"

echo ""
echo "3. 测试 RD-Agent 导入..."
python -c "
from rdagent.app.qlib_rd_loop.factor import main as fin_factor
from rdagent.app.general_model.general_model import extract_models_and_implement as general_model
print('✅ RD-Agent 模块导入成功')
" 2>&1 | grep -v "fitz"

echo ""
echo "=== 测试完成 ==="
