from pydantic import BaseModel, Field


class _LinkPlanBase(BaseModel):
    run_id: int
    default_cap: int = Field(default=1, ge=0, le=100000)
    # {章节: {"out": n, "in": n}}，只录入需要覆盖默认名额的章节；形状在 service 内严格校验
    quotas: dict = Field(default_factory=dict)
    # [["起章","止章"], ...] 必留链接
    required_links: list = Field(default_factory=list)


class LinkPlanInput(_LinkPlanBase):
    pass


class LinkPreviewInput(_LinkPlanBase):
    pass
