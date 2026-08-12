# ============================================================================
# 分镜脚本Prompt总成 —— 提示词内容已迁移至 conf/prompts.yaml
#
# 本文件仅保留常量引用，提示词原文从配置文件加载：
# - 修改提示词 → 编辑 backend/app/conf/prompts.yaml，保存后热加载生效，无需改代码/重启。
# - 模板使用 {placeholder} 占位符，调用时通过 .format(**kwargs) 填充。
# ============================================================================

from app.prompts.prompt_loader import get_config

SCREENPLAY_SYSTEM_PROMPT = get_config("SCREENPLAY_SYSTEM_PROMPT", "")
GENERATE_SCREENPLAY_DIRECTION = get_config("GENERATE_SCREENPLAY_DIRECTION", "")
