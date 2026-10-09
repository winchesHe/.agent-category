# flow-ship release + report 协议

提供：① 完成 report 6 字段模板（spec 末尾追加）② release-script 调用约定（默认 / 代跑 / 风险 / 非 moego fallback）

## 完成 report 6 字段模板

追加到 spec 末尾（替换或补充 `## 完成 report` 章节）：

```markdown
## 完成 report

- **完成日期**：YYYY-MM-DD
- **改动文件**：<≤ 5 个 file path + 一句话>
- **步验证**：1 → <命令 / 输出片段> | 2 → <...> | ...
- **偏差**：<spec 改动 git diff / commit log 摘要，或 None>
- **待跟进**：<未做的 / 后续动作，或 None>
- **PR / Commit**：<PR URL 或 commit hash>
```

### 字段填写来源

| 字段 | 来源 | 填法 |
|---|---|---|
| 完成日期 | flow-ship 自己生成 | `date +%Y-%m-%d` |
| 改动文件 | flow-impl 草稿 | copy |
| 步验证 | flow-impl 草稿 | copy |
| 偏差 | flow-impl 草稿（git diff 摘要）| copy（或 `git log -p docs/specs/<slug>.md` 自己补） |
| 待跟进 | flow-impl 草稿 | copy |
| PR / Commit | flow-ship 自己拿 | `git rev-parse HEAD` 或 PR URL |

**6 字段统一**：消除二重模板；flow-ship 是 source of truth（最终落 spec）。

## `moego-mobile` 发布：重建 `online`

`moego-mobile` 不走下面的通用 `release-script`。只有用户明确要求发布，并明确授权删除、重建本地及远程 `online` 时才执行。

### 入场门禁

1. 工作区必须干净；有未提交或未跟踪文件时停止并让用户确认。
2. 待发布 PR 必须已经合入 `production`；不能从 feature 分支直接发布。
3. 先切换到 `production`，再用 `git pull --ff-only origin production` 拉取最新代码；非 fast-forward 时停止，禁止 reset 或强推。
4. 删除任何远程分支前，先用 `git ls-remote` 回读远端 `online` 的精确 SHA。

### 执行顺序

```bash
git checkout production
git pull --ff-only origin production

# 用户已明确授权后，删除旧的本地 online；此时必须位于 production。
git branch -D online 2>/dev/null || true

# 先从最新 production 创建本地 online。
# moego-mobile 的 pre-push hook 不允许从 production 发起 push，
# 因此必须切到 online 后，再删除远程 online。
git checkout -b online production

REMOTE_ONLINE_SHA="$(git ls-remote --heads origin refs/heads/online | awk '{print $1}')"
if [ -n "$REMOTE_ONLINE_SHA" ]; then
  git push \
    --force-with-lease="refs/heads/online:$REMOTE_ONLINE_SHA" \
    origin --delete online
fi

git push --set-upstream origin online
```

不能用 `--no-verify` 绕过 pre-push hook。`--force-with-lease` 中的 SHA 必须来自本轮删除前的远端回读；若 lease 失败，说明远端已被别人更新，应停止并报告，不能重新读取后直接覆盖。

### 发布验收

```bash
PRODUCTION_SHA="$(git rev-parse production)"
ONLINE_SHA="$(git rev-parse online)"
REMOTE_PRODUCTION_SHA="$(git ls-remote --heads origin refs/heads/production | awk '{print $1}')"
REMOTE_ONLINE_SHA="$(git ls-remote --heads origin refs/heads/online | awk '{print $1}')"

test "$PRODUCTION_SHA" = "$ONLINE_SHA"
test "$PRODUCTION_SHA" = "$REMOTE_PRODUCTION_SHA"
test "$PRODUCTION_SHA" = "$REMOTE_ONLINE_SHA"
git status --short --branch
```

只有本地 `production`、本地 `online`、远程 `production`、远程 `online` 四者指向同一 commit，且工作区干净时，才可以报告 Mobile 发布分支操作完成。随后回读 `online` 触发的 GitHub Actions；workflow 仍在运行时只报告“已触发”，不能宣称发布成功。

## release-script 调用约定

### 默认：让用户终端跑

输出格式：

```
代码已合入 main。要发布请在你的终端跑：
  release-script

（脚本是交互式的，会问几个 y/n 确认。Claude 默认不代跑以保安全。）
```

### 用户明示"代跑"

**先给用户风险提示得确认**：

```
release-script 是交互式 Node 脚本，会做：
- 删除已有的 release 分支（如存在）
- 强制切换到 release 分支并 push
- 代跑过程中不可中断（中断可能留下 inconsistent 状态）

确认代跑？（y/n）
```

得用户**明示**确认后才启动：

```
1. 校验当前 branch == main + 已 pull 最新
2. Bash 启动 release-script
3. 监控 stdout 关键提示（如 "Delete remote release branch? (y/n)"）
4. 默认喂 "y"（已得用户授权代跑）
5. 异常 / 超时 → 停止，告诉用户原状态，不强行继续
```

### 非 moego 项目 fallback

`which release-script` 不在 PATH → 跳过 release 步骤，给"自定义发布"提示：

```
当前项目无 release-script。你可以：
- 手动跑标准发布（如 pnpm release / npm publish）
- 给我 release 命令，我代跑
```

## release-script 实际行为参考

- **脚本位置**：`$(which release-script)`（fnm 全局 bin）
- **脚本流程**：
  1. 检查在 main 分支 + 远程最新 commits
  2. 检查 / 删除已有的远程 release 分支（有 prompt 确认）
  3. 切换到 release 分支（删除已存在的本地 release 分支）
  4. push release 分支到远程
  5. 完成 release 操作

**安全注意**：脚本会自动删除 release 分支——代跑时 Claude 默认喂 `y`，所以必须用户**明示**授权才代跑。
