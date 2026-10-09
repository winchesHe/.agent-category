import json
import os
import re
import subprocess
from hashlib import sha256
from html import escape, unescape
from urllib.parse import urlsplit

from .errors import AuthError, BusinessError, ConfigError, TimeoutError

QUICK_WIN_ID_PATTERN = re.compile(r"\bQW-[A-F0-9]{8}\b")
QUICK_WIN_CHECKBOX_PATTERN = re.compile(
    r"<checkbox\b(?P<attributes>[^>]*)>(?P<body>.*?)</checkbox>",
    flags=re.DOTALL,
)


def _checked_quick_win_ids(content):
    checked = set()
    for match in QUICK_WIN_CHECKBOX_PATTERN.finditer(str(content or "")):
        if not re.search(r'\bdone="true"', match.group("attributes")):
            continue
        candidate = QUICK_WIN_ID_PATTERN.search(match.group("body"))
        if candidate:
            checked.add(candidate.group(0))
    return checked


def _merge_checked_quick_win_ids(content, checked_ids):
    checked = set(checked_ids or ())

    def replace(match):
        candidate = QUICK_WIN_ID_PATTERN.search(match.group("body"))
        if not candidate or candidate.group(0) not in checked:
            return match.group(0)
        attributes = re.sub(
            r'\bdone="(?:true|false)"',
            'done="true"',
            match.group("attributes"),
            count=1,
        )
        return f"<checkbox{attributes}>{match.group('body')}</checkbox>"

    return QUICK_WIN_CHECKBOX_PATTERN.sub(replace, str(content or ""))


def wiki_token(url):
    match = re.fullmatch(r"/wiki/([A-Za-z0-9]+)", urlsplit(url).path.rstrip("/"))
    if not match:
        raise ConfigError("飞书 Wiki URL 格式无效")
    return match.group(1)


def resolve_wiki(config):
    token = wiki_token(config.wiki_url)
    command = [
        config.lark_cli,
        "wiki",
        "spaces",
        "get_node",
        "--params",
        json.dumps({"token": token}, separators=(",", ":")),
        "--format",
        "json",
        "--as",
        "user",
    ]
    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=config.timeout,
        )
        payload = json.loads(result.stdout)
    except FileNotFoundError as exc:
        raise ConfigError("找不到 lark-cli") from exc
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError("解析飞书 Wiki 超时") from exc
    except (subprocess.CalledProcessError, ValueError) as exc:
        raise BusinessError("lark-cli 未返回有效 Wiki 结果") from exc
    if not payload.get("ok"):
        error = payload.get("error", {})
        if error.get("type") in {"auth", "permission"}:
            raise AuthError("lark-cli 无权访问配置的 Wiki")
        raise BusinessError(error.get("message") or "解析 Wiki 失败")
    node = payload.get("data", {}).get("node", {})
    return {
        "url": config.wiki_url,
        "nodeToken": node.get("node_token"),
        "objectToken": node.get("obj_token"),
        "objectType": node.get("obj_type"),
        "spaceId": node.get("space_id"),
        "title": node.get("title"),
        "hasChild": bool(node.get("has_child")),
    }


class LarkWeeklyPublisher:
    def __init__(self, config):
        self.config = config
        self.root = resolve_wiki(config)
        if self.root.get("objectType") != "docx":
            raise BusinessError("飞书根 Wiki 必须是 docx 页面")
        if not self.root.get("nodeToken") or not self.root.get("spaceId"):
            raise BusinessError("飞书根 Wiki 缺少 node_token 或 space_id")

    def _run(self, args, *, input_text=None):
        env = dict(os.environ)
        env["LARKSUITE_CLI_NO_UPDATE_NOTIFIER"] = "1"
        env["LARKSUITE_CLI_NO_SKILLS_NOTIFIER"] = "1"
        try:
            result = subprocess.run(
                [self.config.lark_cli, *args],
                input=input_text,
                check=True,
                capture_output=True,
                text=True,
                timeout=max(90, self.config.timeout),
                env=env,
            )
            payload = json.loads(result.stdout)
        except FileNotFoundError as exc:
            raise ConfigError("找不到 lark-cli") from exc
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError("飞书文档操作超时") from exc
        except subprocess.CalledProcessError as exc:
            try:
                error = json.loads(exc.stderr).get("error", {})
            except ValueError:
                error = {}
            if error.get("type") in {"authorization", "permission"}:
                raise AuthError(error.get("message") or "飞书鉴权失败") from exc
            raise BusinessError(error.get("message") or "飞书文档操作失败") from exc
        except ValueError as exc:
            raise BusinessError("lark-cli 未返回有效 JSON") from exc
        if not payload.get("ok"):
            raise BusinessError(payload.get("error", {}).get("message") or "飞书操作失败")
        return payload

    def _list_children(self, parent_token):
        payload = self._run(
            [
                "wiki",
                "+node-list",
                "--space-id",
                str(self.root["spaceId"]),
                "--parent-node-token",
                parent_token,
                "--page-all",
                "--page-limit",
                "20",
                "--format",
                "json",
                "--as",
                "user",
            ]
        )
        return payload.get("data", {}).get("nodes", [])

    def _find_doc_node(self, parent_token, title):
        matches = [
            node
            for node in self._list_children(parent_token)
            if node.get("title") == title and node.get("obj_type") == "docx"
        ]
        if len(matches) > 1:
            raise BusinessError(f"飞书目录下存在重名文档：{title}")
        return matches[0] if matches else None

    def inspect_month(self, *, year_title, month_title, scope, weekly_marker, monthly_title):
        year_node = self._find_doc_node(self.root["nodeToken"], year_title)
        if not year_node:
            return {"yearNode": None, "monthNode": None, "weeklyPages": [], "monthlyPage": None}
        month_node = self._find_doc_node(year_node["node_token"], month_title)
        if not month_node:
            return {
                "yearNode": year_node,
                "monthNode": None,
                "weeklyPages": [],
                "monthlyPage": None,
            }
        origin = self._origin()
        pattern = re.compile(
            r"^(?P<iso_year>\d{4})-W(?P<iso_week>\d{2})｜"
            r"(?P<start_month>\d{2})\.(?P<start_day>\d{2})–"
            r"(?P<end_month>\d{2})\.(?P<end_day>\d{2})｜"
            + re.escape(str(scope).strip())
            + r" 反馈总览$"
        )
        weekly_pages = []
        monthly_page = None
        for node in self._list_children(month_node["node_token"]):
            if node.get("obj_type") != "docx" or not node.get("obj_token"):
                continue
            title = str(node.get("title") or "")
            if title == monthly_title:
                content = self._fetch(node["obj_token"])
                monthly_page = {
                    "title": title,
                    "nodeToken": node.get("node_token"),
                    "documentToken": node.get("obj_token"),
                    "url": f"{origin}/wiki/{node.get('node_token')}",
                    "contentHash": sha256(content.encode("utf-8")).hexdigest(),
                    "managed": "MFC_MANAGED_MONTHLY_V1" in content,
                }
                continue
            match = pattern.fullmatch(title)
            if not match:
                continue
            calendar_year = int(year_title)
            start = f"{calendar_year:04d}-{match.group('start_month')}-{match.group('start_day')}"
            end_year = calendar_year + (
                1
                if int(match.group("end_month")) < int(match.group("start_month"))
                else 0
            )
            end = f"{end_year:04d}-{match.group('end_month')}-{match.group('end_day')}"
            content = self._fetch(node["obj_token"])
            weekly_pages.append(
                {
                    "title": title,
                    "isoWeek": (
                        f"{match.group('iso_year')}-W{match.group('iso_week')}"
                    ),
                    "start": start,
                    "end": end,
                    "nodeToken": node.get("node_token"),
                    "documentToken": node.get("obj_token"),
                    "url": f"{origin}/wiki/{node.get('node_token')}",
                    "managed": weekly_marker in content,
                }
            )
        return {
            "yearNode": year_node,
            "monthNode": month_node,
            "weeklyPages": weekly_pages,
            "monthlyPage": monthly_page,
        }

    def _ensure_doc_node(self, parent_token, title, *, recover_timeout=False):
        existing = self._find_doc_node(parent_token, title)
        if existing:
            return existing, False

        base = [
            "wiki",
            "+node-create",
            "--parent-node-token",
            parent_token,
            "--obj-type",
            "docx",
            "--title",
            title,
            "--format",
            "json",
            "--as",
            "user",
        ]
        self._run([*base, "--dry-run"])
        try:
            payload = self._run(base)
        except TimeoutError:
            if not recover_timeout:
                raise
            recovered = self._find_doc_node(parent_token, title)
            if recovered:
                return recovered, True
            raise
        data = payload.get("data", {})
        node = data.get("node") if isinstance(data.get("node"), dict) else data
        if not node.get("node_token") or not node.get("obj_token"):
            raise BusinessError(f"飞书创建文档后缺少 token：{title}")
        return node, True

    def _prepare_dashboard_detail_node(
        self,
        parent_token,
        *,
        title,
        ownership_marker,
        managed_child_marker,
        expected_existing=None,
    ):
        actual = self._find_doc_node(parent_token, title)
        if expected_existing and (
            not actual
            or actual.get("node_token") != expected_existing.get("node_token")
        ):
            raise BusinessError(f"飞书分析明细在写入前发生变化：{title}")
        if actual:
            existing_content = self._fetch(actual["obj_token"])
            if (
                managed_child_marker not in existing_content
                or ownership_marker not in existing_content
            ):
                raise BusinessError(
                    f"同名飞书分析明细不是 Collector 托管文档：{title}"
                )
            return actual, False, False

        # 先用绑定 ownership 的稳定 pending 标题创建。创建或首次覆盖中断后，
        # 重跑可精确找回该节点；正文完成后再显式更新 Wiki 节点标题。
        identity, pending_marker = self._dashboard_detail_pending_identity(
            title, ownership_marker
        )
        pending_title = f"{title}｜MFC-pending-{identity}"
        pending_node, pending_created = self._ensure_doc_node(
            parent_token, pending_title, recover_timeout=True
        )
        pending_content = self._fetch(pending_node["obj_token"])
        has_pending_identity = all(
            marker in pending_content
            for marker in (
                managed_child_marker,
                ownership_marker,
                pending_marker,
            )
        )
        if self._is_blank_pending_content(pending_content, pending_title):
            pending_content = (
                f"<title>{escape(pending_title)}</title>"
                f'<p><span text-color="gray">{escape(managed_child_marker)}</span></p>'
                f'<p><span text-color="gray">{escape(ownership_marker)}</span></p>'
                f'<p><span text-color="gray">{escape(pending_marker)}</span></p>'
                "<p>分析明细正在生成，重试会继续更新本页。</p>"
            )
            self._overwrite_with_attempt_marker(
                pending_node["obj_token"], pending_content, pending_marker
            )
        elif not has_pending_identity:
            raise BusinessError(
                f"同名飞书 pending 分析明细不是 Collector 托管文档：{title}"
            )
        return pending_node, pending_created, True

    @staticmethod
    def _is_blank_pending_content(content, pending_title):
        value = str(content or "").strip()
        if value in {"", "Untitled", pending_title}:
            return True
        title_match = re.fullmatch(
            r"<title(?:\s+[^>]*)?>(.*?)</title>(.*)",
            value,
            flags=re.DOTALL,
        )
        if not title_match:
            return False
        title_text = unescape(title_match.group(1)).strip()
        if title_text != pending_title:
            return False
        remainder = title_match.group(2)
        return bool(
            re.fullmatch(
                r"(?:\s*<p(?:\s+[^>]*)?>\s*(?:<br\s*/?>)?\s*</p>)*\s*",
                remainder,
                flags=re.DOTALL,
            )
        )

    @staticmethod
    def _dashboard_detail_pending_identity(title, ownership_marker):
        identity = sha256(
            f"{title}\0{ownership_marker}".encode("utf-8")
        ).hexdigest()[:12]
        return identity, f"MFC_PENDING_DASHBOARD_DETAIL_V1|identity={identity}"

    def _overwrite_with_attempt_marker(self, doc_token, content, attempt_marker):
        try:
            self._overwrite(doc_token, content)
        except TimeoutError:
            recovered_content = self._fetch(doc_token)
            if attempt_marker not in recovered_content:
                raise

    def _update_wiki_node_title(self, parent_token, node_token, title):
        path = (
            f"/open-apis/wiki/v2/spaces/{self.root['spaceId']}"
            f"/nodes/{node_token}/update_title"
        )
        base = [
            "api",
            "POST",
            path,
            "--data",
            json.dumps({"title": title}, ensure_ascii=False),
            "--format",
            "json",
            "--as",
            "user",
        ]
        self._run([*base, "--dry-run"])
        try:
            self._run(base)
        except TimeoutError:
            renamed = self._find_doc_node(parent_token, title)
            if not renamed or renamed.get("node_token") != node_token:
                raise

    def _origin(self):
        parsed = urlsplit(self.config.wiki_url)
        return f"{parsed.scheme}://{parsed.netloc}"

    def _move_node(self, node_token, target_parent_token, title):
        base = [
            "wiki",
            "+move",
            "--node-token",
            node_token,
            "--target-parent-token",
            target_parent_token,
            "--format",
            "json",
            "--as",
            "user",
        ]
        self._run([*base, "--dry-run"])
        self._run(base)
        moved = self._find_doc_node(target_parent_token, title)
        if not moved or moved.get("node_token") != node_token:
            raise BusinessError(f"飞书文档移动后回读失败：{title}")
        return moved

    def _overwrite(self, doc_token, content):
        base = [
            "docs",
            "+update",
            "--api-version",
            "v2",
            "--doc",
            doc_token,
            "--command",
            "overwrite",
            "--doc-format",
            "xml",
            "--content",
            "-",
            "--format",
            "json",
            "--as",
            "user",
        ]
        self._run([*base, "--dry-run"], input_text=content)
        payload = self._run(base, input_text=content)
        data = payload.get("data", {})
        result = data.get("result")
        if result and result != "success":
            warnings = data.get("warnings") or []
            raise BusinessError(
                f"飞书文档覆盖未完全成功：result={result}, warnings={warnings[:3]}"
            )
        return payload

    def _fetch(self, doc_token):
        payload = self._run(
            [
                "docs",
                "+fetch",
                "--api-version",
                "v2",
                "--doc",
                doc_token,
                "--scope",
                "full",
                "--detail",
                "simple",
                "--format",
                "json",
                "--as",
                "user",
            ]
        )
        return payload.get("data", {}).get("document", {}).get("content", "")

    def _initialize_index(self, node, title, description):
        content = (
            f"<title>{escape(title)}</title><p>{escape(description)}</p>"
            "<sub-page-list></sub-page-list>"
        )
        self._overwrite(node["obj_token"], content)

    def _retire_stale_child_documents(
        self,
        week_node,
        *,
        expected_titles,
        managed_child_prefix,
        managed_child_marker,
    ):
        if not managed_child_prefix or not managed_child_marker:
            return []
        retired = []
        for node in self._list_children(week_node["node_token"]):
            title = str(node.get("title") or "")
            if (
                title in expected_titles
                or not title.startswith(managed_child_prefix)
                or node.get("obj_type") != "docx"
                or not node.get("obj_token")
            ):
                continue
            existing = self._fetch(node["obj_token"])
            if managed_child_marker not in existing:
                continue
            content = (
                f"<title>{escape(title)}</title>"
                f'<p><span text-color="gray">{escape(managed_child_marker)}</span></p>'
                "<callout emoji=\"📌\" background-color=\"light-gray\" "
                "border-color=\"gray\"><p>本页已失效，最新周报不再包含这些反馈明细。"
                "</p></callout>"
            )
            self._overwrite(node["obj_token"], content)
            verified = self._fetch(node["obj_token"])
            if managed_child_marker not in verified or "本页已失效" not in verified:
                raise BusinessError(f"飞书旧源数据文档收敛失败：{title}")
            retired.append(title)
        return retired

    def publish(
        self,
        *,
        year_title,
        month_title,
        week_container_title,
        source_title,
        content,
        markers,
        managed_week_marker,
        child_documents=None,
        source_marker=None,
        source_ownership_marker=None,
        managed_child_prefix=None,
        managed_child_marker=None,
    ):
        if not source_marker or not source_ownership_marker:
            raise BusinessError("来源看板缺少 Collector 托管身份")

        existing_year = self._find_doc_node(self.root["nodeToken"], year_title)
        existing_month = (
            self._find_doc_node(existing_year["node_token"], month_title)
            if existing_year
            else None
        )
        existing_week = (
            self._find_doc_node(existing_month["node_token"], week_container_title)
            if existing_month
            else None
        )
        if existing_week:
            existing_week_content = self._fetch(existing_week["obj_token"])
            if managed_week_marker not in existing_week_content:
                raise BusinessError("同名飞书周总览不是 Collector 托管文档")
        existing_source = (
            self._find_doc_node(existing_week["node_token"], source_title)
            if existing_week
            else None
        )
        legacy_source = (
            self._find_doc_node(existing_month["node_token"], source_title)
            if existing_month
            else None
        )
        if existing_source and legacy_source:
            raise BusinessError("飞书周目录与月份目录同时存在同名来源页")
        for candidate in (existing_source, legacy_source):
            if not candidate:
                continue
            candidate_content = self._fetch(candidate["obj_token"])
            if source_ownership_marker not in candidate_content:
                raise BusinessError("同名飞书来源页不是 Collector 托管文档")

        year_node, year_created = self._ensure_doc_node(
            self.root["nodeToken"], year_title
        )
        if year_created:
            self._initialize_index(year_node, year_title, "按月份归档反馈周报。")

        month_node, month_created = self._ensure_doc_node(
            year_node["node_token"], month_title
        )
        if month_created:
            self._initialize_index(month_node, month_title, "按周归档反馈采集结果。")

        week_node, week_created = self._ensure_doc_node(
            month_node["node_token"], week_container_title
        )
        if week_created:
            self._overwrite(
                week_node["obj_token"],
                (
                    f"<title>{escape(week_container_title)}</title>"
                    f'<p><span text-color="gray">{escape(managed_week_marker)}</span></p>'
                    "<callout emoji=\"📌\" background-color=\"light-gray\" "
                    "border-color=\"gray\"><p>来源数据已发布；周度分析总览尚未生成。"
                    "</p></callout>"
                ),
            )
        source_node = existing_source
        source_created = False
        source_moved = False
        if not source_node:
            if legacy_source:
                source_node = self._move_node(
                    legacy_source["node_token"], week_node["node_token"], source_title
                )
                source_moved = True
            else:
                source_node, source_created = self._ensure_doc_node(
                    week_node["node_token"], source_title
                )
                if source_created:
                    self._overwrite(
                        source_node["obj_token"],
                        (
                            f"<title>{escape(source_title)}</title>"
                            f'<p><span text-color="gray">{escape(source_marker)}</span></p>'
                            "<p>来源看板正在生成，重试会继续覆盖本页。</p>"
                        ),
                    )
        source_links = []
        for document in child_documents or []:
            child_node, child_created = self._ensure_doc_node(
                source_node["node_token"], document["title"]
            )
            if not child_created:
                child_content = self._fetch(child_node["obj_token"])
                if (
                    not managed_child_marker
                    or managed_child_marker not in child_content
                ):
                    raise BusinessError(
                        f"同名飞书源数据页不是 Collector 托管文档：{document['title']}"
                    )
            self._overwrite(child_node["obj_token"], document["content"])
            child_content = self._fetch(child_node["obj_token"])
            if (
                document["title"] not in child_content
                or not managed_child_marker
                or managed_child_marker not in child_content
            ):
                raise BusinessError(
                    f"飞书源数据文档写后回读失败：{document['title']}"
                )
            source_links.append(
                f'<li><cite type="doc" doc-id="{child_node["obj_token"]}"></cite></li>'
            )
        if source_links:
            content = content.replace(
                "<p>__SOURCE_DOCUMENTS__</p>",
                "<p>源数据量较大，已拆分为以下子文档：</p><ul>"
                + "".join(source_links)
                + "</ul>",
            )
        self._overwrite(source_node["obj_token"], content)
        fetched = self._fetch(source_node["obj_token"])
        missing = [marker for marker in markers if marker not in fetched]
        if missing:
            raise BusinessError(f"飞书周报写后回读缺少标记：{', '.join(missing)}")
        retired_children = self._retire_stale_child_documents(
            source_node,
            expected_titles={document["title"] for document in child_documents or []},
            managed_child_prefix=managed_child_prefix,
            managed_child_marker=managed_child_marker,
        )

        origin = self._origin()
        return {
            "created": source_created,
            "moved": source_moved,
            "yearNode": year_node["node_token"],
            "monthNode": month_node["node_token"],
            "weekNode": week_node["node_token"],
            "sourceNode": source_node["node_token"],
            "documentToken": source_node["obj_token"],
            "weekUrl": f"{origin}/wiki/{week_node['node_token']}",
            "url": f"{origin}/wiki/{source_node['node_token']}",
            "verified": True,
            "retiredChildDocuments": retired_children,
        }

    def publish_dashboard(
        self,
        *,
        year_title,
        month_title,
        week_title,
        content,
        markers,
        managed_marker,
        source_reports,
        child_documents=None,
        managed_child_marker=None,
        allow_empty_sources=False,
    ):
        required_sources = ("canny", "intercom", "jira", "facebook")
        reports_by_source = {
            item.get("sourceKey"): item
            for item in source_reports
            if item.get("sourceKey") in required_sources
        }
        missing_sources = [
            source
            for source in required_sources
            if source not in reports_by_source
            or reports_by_source[source].get("status") != "ready"
        ]
        if missing_sources:
            raise BusinessError(
                "正式周总览必须包含四个已就绪来源："
                + ", ".join(missing_sources)
            )
        empty_sources = [
            source
            for source in required_sources
            if int(reports_by_source[source].get("included") or 0) == 0
        ]
        if empty_sources and not allow_empty_sources:
            raise BusinessError(
                "正式周总览四个来源都必须有入选数据："
                + ", ".join(empty_sources)
            )

        year_node = self._find_doc_node(self.root["nodeToken"], year_title)
        if not year_node:
            raise BusinessError("正式周总览缺少年份目录")
        month_node = self._find_doc_node(year_node["node_token"], month_title)
        if not month_node:
            raise BusinessError("正式周总览缺少月份目录")
        week_node = self._find_doc_node(month_node["node_token"], week_title)
        if not week_node:
            raise BusinessError("正式周总览缺少已发布的周目录")
        existing_week = self._fetch(week_node["obj_token"])
        if managed_marker not in existing_week:
            raise BusinessError("同名飞书周度总览不是 Collector 托管文档")

        week_children = self._list_children(week_node["node_token"])
        reports_by_title = {}
        duplicate_report_titles = set()
        for node in week_children:
            title = node.get("title")
            if node.get("obj_type") != "docx" or not node.get("obj_token") or not title:
                continue
            if title in reports_by_title:
                duplicate_report_titles.add(title)
            reports_by_title[title] = node
        source_labels = {
            "canny": "Canny",
            "intercom": "Intercom",
            "jira": "Jira CS",
            "facebook": "Facebook Community",
        }
        report_links = []
        linked_reports = {}
        missing_reports = []
        for item in source_reports:
            source = item["sourceKey"]
            label = source_labels[source]
            title = item.get("reportTitle")
            if item.get("status") != "ready":
                report_links.append(f"<li>{label}：本周期未提供 manifest。</li>")
                continue
            if not title:
                report_links.append(f"<li>{label}：当前仅采集，暂无独立源周报。</li>")
                continue
            if title in duplicate_report_titles:
                raise BusinessError(f"飞书周目录下存在重名来源周报：{title}")
            node = reports_by_title.get(title)
            if not node:
                missing_reports.append(source)
                report_links.append(
                    f"<li>{label}：{escape(title)}（源周报尚未发布）</li>"
                )
                continue
            managed_source_marker = item.get("managedMarker")
            source_content = self._fetch(node["obj_token"])
            if not managed_source_marker or managed_source_marker not in source_content:
                raise BusinessError(
                    f"来源子看板与本次 manifest 不一致：{source}"
                )
            report_links.append(
                f'<li>{label}：<cite type="doc" doc-id="{node["obj_token"]}"></cite></li>'
            )
            linked_reports[source] = {
                "title": title,
                "documentToken": node["obj_token"],
                "nodeToken": node.get("node_token"),
            }
        if missing_reports:
            raise BusinessError(
                "正式周总览缺少来源子看板：" + ", ".join(missing_reports)
            )

        detail_documents = list(child_documents or [])
        detail_titles = [str(item.get("title") or "") for item in detail_documents]
        if len(detail_titles) != len(set(detail_titles)):
            raise BusinessError("周总览分析明细包含重名子文档")
        if detail_documents and not managed_child_marker:
            raise BusinessError("周总览分析明细缺少 Collector 托管标记")
        preserved_checked_quick_wins = set()
        stale_managed_details = []
        for document in detail_documents:
            title = str(document.get("title") or "")
            placeholder = str(document.get("placeholder") or "")
            child_content = str(document.get("content") or "")
            ownership_marker = str(document.get("ownershipMarker") or "")
            if not title or not placeholder or not child_content or not ownership_marker:
                raise BusinessError("周总览分析明细结构无效")
            if placeholder not in content:
                raise BusinessError(f"周总览缺少分析明细入口：{title}")
            if (
                managed_child_marker not in child_content
                or ownership_marker not in child_content
            ):
                raise BusinessError(f"周总览分析明细缺少托管身份：{title}")
            if title in duplicate_report_titles:
                raise BusinessError(f"飞书周目录下存在重名分析明细：{title}")
            existing_child = reports_by_title.get(title)
            if existing_child:
                existing_child_content = self._fetch(existing_child["obj_token"])
                if (
                    managed_child_marker not in existing_child_content
                    or ownership_marker not in existing_child_content
                ):
                    raise BusinessError(
                        f"同名飞书分析明细不是 Collector 托管文档：{title}"
                    )
                preserved_checked_quick_wins.update(
                    _checked_quick_win_ids(existing_child_content)
                )
        if managed_child_marker:
            for node in week_children:
                title = str(node.get("title") or "")
                if (
                    title in detail_titles
                    or node.get("obj_type") != "docx"
                    or not node.get("obj_token")
                ):
                    continue
                existing_content = self._fetch(node["obj_token"])
                if managed_child_marker not in existing_content:
                    continue
                checked_ids = _checked_quick_win_ids(existing_content)
                preserved_checked_quick_wins.update(checked_ids)
                stale_managed_details.append(
                    {
                        "title": title,
                        "documentToken": node["obj_token"],
                        "nodeToken": node.get("node_token"),
                        "checkedQuickWinIds": sorted(checked_ids),
                    }
                )

        source_report_links = "<ul>" + "".join(report_links) + "</ul>"
        content = content.replace("<p>__SOURCE_REPORTS__</p>", source_report_links)
        linked_details = {}
        for document in detail_documents:
            child_node, child_created, needs_rename = (
                self._prepare_dashboard_detail_node(
                    week_node["node_token"],
                    title=document["title"],
                    ownership_marker=document["ownershipMarker"],
                    managed_child_marker=managed_child_marker,
                    expected_existing=reports_by_title.get(document["title"]),
                )
            )
            child_content = str(document["content"]).replace(
                "<p>__SOURCE_REPORTS__</p>", source_report_links
            )
            child_content = _merge_checked_quick_win_ids(
                child_content, preserved_checked_quick_wins
            )
            expected_checked = _checked_quick_win_ids(child_content)
            if needs_rename:
                _identity, pending_marker = self._dashboard_detail_pending_identity(
                    document["title"], document["ownershipMarker"]
                )
                child_content += (
                    f'<p><span text-color="gray">{escape(pending_marker)}</span></p>'
                )
            content_digest = sha256(child_content.encode("utf-8")).hexdigest()
            attempt_marker = f"MFC_DETAIL_CONTENT_SHA256|value={content_digest}"
            child_content += (
                f'<p><span text-color="gray">{escape(attempt_marker)}</span></p>'
            )
            self._overwrite_with_attempt_marker(
                child_node["obj_token"], child_content, attempt_marker
            )
            fetched_child_content = self._fetch(child_node["obj_token"])
            missing_child_markers = [
                marker
                for marker in [*document.get("markers", []), attempt_marker]
                if marker not in fetched_child_content
            ]
            if missing_child_markers:
                raise BusinessError(
                    f"飞书分析明细写后回读缺少标记：{document['title']}"
                )
            actual_checked = _checked_quick_win_ids(fetched_child_content)
            if expected_checked != actual_checked:
                raise BusinessError(
                    f"飞书分析明细勾选状态回读不一致：{document['title']}"
                )
            if needs_rename:
                self._update_wiki_node_title(
                    week_node["node_token"],
                    child_node["node_token"],
                    document["title"],
                )
            final_node = self._find_doc_node(
                week_node["node_token"], document["title"]
            )
            if (
                not final_node
                or final_node.get("node_token") != child_node.get("node_token")
            ):
                raise BusinessError(
                    f"飞书分析明细标题收敛失败：{document['title']}"
                )
            child_node = final_node
            content = content.replace(
                document["placeholder"],
                f'<p><cite type="doc" doc-id="{child_node["obj_token"]}"></cite></p>',
            )
            linked_details[document.get("key") or document["title"]] = {
                "title": document["title"],
                "created": child_created,
                "documentToken": child_node["obj_token"],
                "nodeToken": child_node.get("node_token"),
            }
        self._overwrite(week_node["obj_token"], content)
        fetched = self._fetch(week_node["obj_token"])
        missing_markers = [marker for marker in markers if marker not in fetched]
        if missing_markers:
            raise BusinessError(
                f"飞书总看板周报回读缺少标记：{', '.join(missing_markers)}"
            )
        origin = self._origin()
        return {
            "weekCreated": False,
            "yearNode": year_node["node_token"],
            "monthNode": month_node["node_token"],
            "weekNode": week_node["node_token"],
            "weekUrl": f"{origin}/wiki/{week_node['node_token']}",
            "linkedSourceReports": linked_reports,
            "linkedDetailDocuments": linked_details,
            "preservedCheckedQuickWinIds": sorted(preserved_checked_quick_wins),
            "staleManagedDetailDocuments": stale_managed_details,
            "missingSourceReports": missing_reports,
            "verified": True,
        }

    def publish_monthly(
        self,
        *,
        year_title,
        month_title,
        title,
        content,
        markers,
        monthly_marker,
        weekly_marker,
        weekly_pages,
        adopt_existing_hash="",
    ):
        year_node = self._find_doc_node(self.root["nodeToken"], year_title)
        if not year_node:
            raise BusinessError("正式月度汇总缺少年份目录")
        month_node = self._find_doc_node(year_node["node_token"], month_title)
        if not month_node:
            raise BusinessError("正式月度汇总缺少月份目录")
        month_children = self._list_children(month_node["node_token"])
        by_title = {}
        duplicates = set()
        for node in month_children:
            child_title = str(node.get("title") or "")
            if child_title in by_title:
                duplicates.add(child_title)
            by_title[child_title] = node
        for page in weekly_pages:
            expected_title = str(page.get("title") or "")
            if expected_title in duplicates:
                raise BusinessError(f"飞书月份目录存在重复周总览：{expected_title}")
            node = by_title.get(expected_title)
            if (
                not node
                or node.get("node_token") != page.get("nodeToken")
                or node.get("obj_token") != page.get("documentToken")
            ):
                raise BusinessError(f"月度输入周总览在写入前发生变化：{expected_title}")
            weekly_content = self._fetch(node["obj_token"])
            if weekly_marker not in weekly_content:
                raise BusinessError(f"月度输入周总览不是 Collector 托管文档：{expected_title}")

        existing = by_title.get(title)
        created = False
        adopted = False
        if existing:
            existing_content = self._fetch(existing["obj_token"])
            if "MFC_MANAGED_MONTHLY_V1" not in existing_content:
                actual_hash = sha256(existing_content.encode("utf-8")).hexdigest()
                if not adopt_existing_hash or actual_hash != adopt_existing_hash:
                    raise BusinessError("同名飞书月度页不是 Collector 托管文档")
                adopted = True
            monthly_node = existing
        else:
            monthly_node, created = self._ensure_doc_node(month_node["node_token"], title)
        self._overwrite(monthly_node["obj_token"], content)
        fetched = self._fetch(monthly_node["obj_token"])
        missing = [marker for marker in [monthly_marker, *markers] if marker not in fetched]
        if missing:
            raise BusinessError("飞书月度汇总写后回读缺少标记：" + ", ".join(missing))
        return {
            "created": created,
            "adopted": adopted,
            "yearNode": year_node["node_token"],
            "monthNode": month_node["node_token"],
            "monthlyNode": monthly_node["node_token"],
            "documentToken": monthly_node["obj_token"],
            "url": f"{self._origin()}/wiki/{monthly_node['node_token']}",
            "verified": True,
        }
