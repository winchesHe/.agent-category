from copy import deepcopy

from .errors import BusinessError, ConfigError


class GreyMutationService:
    def __init__(self, client):
        self.client = client

    def _validate_services(self, namespace, service_map):
        available = self.client.branches(namespace)
        for service, branch in service_map.items():
            if service not in available:
                raise ConfigError(f"Grey 服务不存在：{service}")
            if branch not in available[service]:
                raise ConfigError(
                    "Grey 分支不存在：{}={}，可选 {}".format(
                        service, branch, ", ".join(available[service])
                    )
                )

    def _verify(self, actual, expected, fields):
        mismatched = [
            field for field in fields if actual.get(field) != expected.get(field)
        ]
        if mismatched:
            raise BusinessError(
                "Grey 写后回读不一致：{}".format(", ".join(mismatched))
            )

    def create(
        self, namespace, name, description, jira_tickets, service_map, apply=False
    ):
        if self.client.get_by_name(name):
            raise BusinessError(f"Grey 规则已存在：{name}")
        self._validate_services(namespace, service_map)
        item = {
            "namespace": namespace,
            "name": name,
            "description": description or "",
            "jiraTickets": jira_tickets or [],
            "svcBranchMap": service_map,
        }
        plan = {"mode": "apply" if apply else "plan", "operation": "create", "after": item}
        if not apply:
            return plan
        created = self.client.insert(item)
        item_id = created.get("id")
        actual = self.client.get({"id": item_id}) if item_id else created
        self._verify(
            actual,
            item,
            ("namespace", "name", "description", "jiraTickets", "svcBranchMap"),
        )
        plan["result"] = actual
        return plan

    def update(self, selector, changes, expected_updated_at=None, apply=False):
        before = self.client.get(selector)
        after = deepcopy(before)
        after.update({key: value for key, value in changes.items() if value is not None})
        if after.get("name") != before.get("name"):
            conflict = self.client.get_by_name(after["name"])
            if conflict and conflict.get("id") != before.get("id"):
                raise BusinessError("Grey 规则已存在：{}".format(after["name"]))
        service_map = after.get("svcBranchMap", {})
        if service_map:
            self._validate_services(after.get("namespace", "ns-testing"), service_map)
        plan = {
            "mode": "apply" if apply else "plan",
            "operation": "update",
            "before": before,
            "after": after,
            "expectedUpdatedAt": before.get("updatedAt"),
        }
        if not apply:
            return plan
        if not expected_updated_at:
            raise ConfigError("--apply update 必须传 --expected-updated-at")
        current = self.client.get({"id": before["id"]})
        if current.get("updatedAt") != expected_updated_at:
            raise BusinessError("规则已被更新；请重新生成 plan")
        result = self.client.update(after)
        actual = self.client.get({"id": result.get("id", before["id"])})
        self._verify(
            actual,
            after,
            ("name", "description", "jiraTickets", "svcBranchMap"),
        )
        plan["result"] = actual
        return plan

    def delete(
        self, selector, confirm=None, expected_updated_at=None, apply=False
    ):
        before = self.client.get(selector)
        plan = {
            "mode": "apply" if apply else "plan",
            "operation": "delete",
            "before": before,
            "snapshot": before,
            "expectedUpdatedAt": before.get("updatedAt"),
        }
        if not apply:
            return plan
        if confirm != before.get("name"):
            raise ConfigError("--confirm 必须与规则名称完全一致")
        if not expected_updated_at:
            raise ConfigError("--apply delete 必须传 --expected-updated-at")
        current = self.client.get({"id": before["id"]})
        if current.get("updatedAt") != expected_updated_at:
            raise BusinessError("规则已被更新；请重新生成 plan")
        self.client.delete(before["id"])
        tombstone = self.client.get_optional({"id": before["id"]})
        if tombstone is not None:
            if not tombstone.get("deletedAt"):
                raise BusinessError("Grey 删除后回读仍存在")
            if self.client.get_by_name(before["name"]) is not None:
                raise BusinessError("Grey 软删除后名称仍可见")
            plan["deletedAt"] = tombstone["deletedAt"]
        plan["deleted"] = True
        return plan

    def copy(
        self,
        selector,
        namespace,
        name,
        description=None,
        jira_tickets=None,
        service_map=None,
        apply=False,
    ):
        source = self.client.get(selector)
        return self.create(
            namespace=namespace or source.get("namespace", "ns-testing"),
            name=name,
            description=description
            if description is not None
            else source.get("description", ""),
            jira_tickets=jira_tickets
            if jira_tickets is not None
            else source.get("jiraTickets", []),
            service_map=service_map
            if service_map is not None
            else source.get("svcBranchMap", {}),
            apply=apply,
        )
