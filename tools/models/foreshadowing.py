"""
伏笔系统数据模型
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict
from datetime import datetime


class ForeshadowingNode(BaseModel):
    """伏笔节点"""

    id: str = Field(..., description="伏笔ID")
    content: str = Field(..., description="伏笔内容描述")
    weight: int = Field(..., ge=1, le=10, description="权重 1-10")
    layer: str = Field(..., description="主线/支线/彩蛋")
    status: str = Field(..., description="埋伏/待收/已收/废弃")
    created_at: str = Field(..., description="创建章节ID")
    target_chapter: Optional[str] = Field(None, description="预期回收章节")
    tags: List[str] = Field(default_factory=list, description="标签")


class ForeshadowingEdge(BaseModel):
    """伏笔 DAG 边"""

    from_: str = Field(..., alias="from", description="来源伏笔ID")
    to: str = Field(..., description="目标伏笔ID或回收点")
    type: str = Field(..., description="依赖/强化/反转")


class ForeshadowingGraph(BaseModel):
    """伏笔 DAG 图"""

    nodes: Dict[str, ForeshadowingNode] = Field(
        default_factory=dict, description="所有伏笔节点"
    )
    edges: List[ForeshadowingEdge] = Field(
        default_factory=list, description="伏笔关系边"
    )
    status: Dict[str, str] = Field(default_factory=dict, description="节点状态映射")
