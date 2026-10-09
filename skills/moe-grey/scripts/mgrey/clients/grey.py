from ..errors import BusinessError

SERVICE = "/moego.api.grey_gateway.v1.GreyGatewayService/"


class GreyClient:
    def __init__(self, base_url, http):
        self.base_url = base_url.rstrip("/")
        self.http = http

    def _post(self, method, payload):
        return self.http.post(self.base_url + SERVICE + method, json=payload)

    def list(self, namespace):
        data = self._post("GetGreyItemList", {"namespace": namespace})
        return data.get("greyItems", data.get("items", []))

    def get(self, selector):
        if selector.get("id"):
            data = self._post("GetGreyItem", {"id": str(selector["id"])})
        else:
            data = self._post("GetGreyItemByName", {"name": selector["name"]})
        return data.get("greyItem", data.get("item", data))

    def get_by_name(self, name):
        try:
            return self.get({"name": name})
        except BusinessError as exc:
            if "404" in str(exc) or "not found" in str(exc).lower():
                return None
            raise

    def get_optional(self, selector):
        try:
            return self.get(selector)
        except BusinessError as exc:
            if "404" in str(exc) or "not found" in str(exc).lower():
                return None
            raise

    def branches(self, namespace):
        data = self._post("GetServiceBranchMap", {"namespace": namespace})
        raw = data.get("svcBranchesMap", data.get("serviceBranchMap", {}))
        result = {}
        for service, branches in raw.items():
            if isinstance(branches, dict):
                branches = branches.get(
                    "name", branches.get("branches", branches.get("values", []))
                )
            result[service] = branches
        return result

    def insert(self, item):
        data = self._post("InsertGreyItem", item)
        return data.get("greyItem", data)

    def update(self, item):
        allowed = ("id", "name", "description", "jiraTickets", "svcBranchMap")
        payload = {key: item[key] for key in allowed if key in item}
        data = self._post("UpdateGreyItem", payload)
        return data.get("greyItem", data)

    def delete(self, item_id):
        return self._post("DeleteGreyItem", {"id": str(item_id)})
