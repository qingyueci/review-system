"""首板布局模块。

该包只保存首板布局自己的运行数据和历史模型资料；不会读取或写入既有复盘
知识库。路由层和页面层可以按需导入其中的独立组件。
"""

from .schemas import (
    CandidateMetrics,
    DragonAnalysisResult,
    ReviewSnapshot,
    RuleDefinition,
)
from .field_registry import FIELD_REGISTRY, default_hard_rule_inputs

__all__ = [
    "CandidateMetrics",
    "DragonAnalysisResult",
    "ReviewSnapshot",
    "RuleDefinition",
    "FIELD_REGISTRY",
    "default_hard_rule_inputs",
]
