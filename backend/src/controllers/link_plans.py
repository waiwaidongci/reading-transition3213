from ..services import link_plans


class LinkPlansController:
    preview = staticmethod(link_plans.preview)
    create = staticmethod(link_plans.create_plan)
    list = staticmethod(link_plans.list_plans)
    get = staticmethod(link_plans.get_plan)
    active = staticmethod(link_plans.active_plan)
    approve = staticmethod(link_plans.approve_plan)
