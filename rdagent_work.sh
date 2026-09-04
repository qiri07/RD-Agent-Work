#!/bin/bash
cd /run/media/onai/MyDisk/Work/RD-Agent-Work
source rdagent-env/bin/activate

# 加载 .env 文件，并将 LITELLM 凭据导出为 litellm 所需的 OPENAI 环境变量
eval "$(python -c "
import os
from dotenv import load_dotenv
load_dotenv('.env', override=True)
if os.environ.get('LITELLM_OPENAI_API_KEY'):
    print(f'export OPENAI_API_KEY=\"{os.environ[\"LITELLM_OPENAI_API_KEY\"]}\"')
if os.environ.get('LITELLM_CHAT_OPENAI_BASE_URL'):
    print(f'export OPENAI_BASE_URL=\"{os.environ[\"LITELLM_CHAT_OPENAI_BASE_URL\"]}\"')
")"

case "$1" in
    fin_factor)
        python -c "
from rdagent.app.qlib_rd_loop.factor import main as fin_factor
import sys
sys.argv = ['rdagent', 'fin_factor'] + sys.argv[1:]
fin_factor()
"
        ;;
    fin_model)
        python -c "
from rdagent.app.qlib_rd_loop.model import main as fin_model
import sys
sys.argv = ['rdagent', 'fin_model'] + sys.argv[1:]
fin_model()
"
        ;;
    fin_quant)
        python -c "
from rdagent.app.qlib_rd_loop.quant import main as fin_quant
import sys
sys.argv = ['rdagent', 'fin_quant'] + sys.argv[1:]
fin_quant()
"
        ;;
    general_model)
        python -c "
from rdagent.app.general_model.general_model import extract_models_and_implement as general_model
import sys
sys.argv = ['rdagent', 'general_model'] + sys.argv[1:]
general_model()
"
        ;;
    health_check)
        python -c "
from rdagent.app.utils.health_check import health_check
import sys
sys.argv = ['rdagent', 'health_check'] + sys.argv[1:]
health_check()
"
        ;;
    *)
        echo "Usage: $0 {fin_factor|fin_model|fin_quant|general_model|health_check}"
        exit 1
        ;;
esac
