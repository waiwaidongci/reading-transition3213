from sqlalchemy import Column, Integer, String, JSON, Text, Index
from ..config.database import Base
from ..config.settings import CONFIG


class LinkPlan(Base):
    """章节链接名额配置的一个版本（草案 / 已批准）。

    每次名额或必留链接改版都新增一行，旧行不可变；config_checksum 标识配置口径。
    active_key 用于跨库兼容的"全局唯一生效版本"约束：生效行写固定值，未生效为 NULL，
    配合唯一索引保证并发批准只有一个版本生效。
    """
    __tablename__ = CONFIG['link_plan_table']
    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, nullable=False)
    version = Column(Integer, nullable=False)
    state = Column(String(20), default='draft')          # draft / approved
    default_cap = Column(Integer, nullable=False, default=1)
    quotas = Column(JSON, nullable=False)                # {章节: {"out":n,"in":n}}
    required_links = Column(JSON, nullable=False)        # [["起","止"], ...]
    config_checksum = Column(String(64), nullable=False)
    result = Column(JSON, nullable=False)                # allocate() 的完整结果快照
    conflicts = Column(JSON, nullable=False, default=list)
    author = Column(String(120), nullable=False)
    approved_by = Column(String(120), default='')
    activated_at = Column(String(40), default='')
    active_key = Column(String(20), nullable=True)
    created_at = Column(String(40), nullable=False)

    __table_args__ = (
        Index('uq_link_active', 'active_key', unique=True),
        Index('ix_link_run_version', 'run_id', 'version'),
    )
