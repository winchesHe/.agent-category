# Kafka 开发、平台操作与排障

- ID：`MDEV-KAFKA-DEBUGGING`
- 适用：MoeGo Kafka 开发接入、平台查消息和消费组，以及请求成功无消息、消费积压或无业务结果。

## 平台入口与使用顺序

管理平台：[kafka.devops.moego.pet](https://kafka.devops.moego.pet/)。通过公司 SSO 登录后，选择与应用 Broker 配置对应的集群；不能只凭相似的 Topic 名判断环境。

已知消息或消费组时可直接查平台；不确定目标名称、路由或编码时先查下面的开发接入。已有可用客户端时也可用 CLI 查询。平台的 SSO 与 Broker 的网络、TLS、IAM 等认证是不同链路，网页登录信息不能直接用作 CLI 凭据。

## 先定位实际发送和消费路径

新增发送或消费功能时先读目标仓库/模块指南，复用已有客户端、注册和配置方式。Go 大仓可从应用目录反查 `backend/common/rpc/database/kafka/` 及其 examples，其他仓库使用自己的实际模块路径：

```bash
rg -n 'SendMessage|RegisterKafkaHandlerService|protocol: kafka|kafka://' 'backend/app/<app>'
```

沿业务入口确认 Producer 确实被调用，Consumer 在启动时装配，并检查编码/解码、路由过滤、处理失败、提交位点和幂等处理的位置。配置了 Topic 或写了 handler，都不等于业务链已接通。

请求成功只说明入口按契约返回。去重、过滤或异步调度都可能使本次请求不产生新消息；先查实际业务分支，不用手工发消息证明业务入口已经接通。

若应用使用 Outbox，依次定位“业务事务 → 待发送记录 → Dispatcher → Producer → Consumer → 业务终态”。Broker 确认后的发送状态落库与消费处理可能并行；不能要求 Consumer 必须等到 Outbox 标记已发送才开始执行。

## 查实际 Topic、组和路由

从目标环境配置与运行版本确认 Broker、Topic、消费组、序列化方式和消息路由头。消费组可能由基础名与应用版本组合，Topic 也可能带环境后缀；以构造代码和实际运行值为准，不从分支名猜测。

Topic 不存在时，同时检查 Broker 的自动创建配置与客户端是否允许、是否实际触发创建。客户端若在启动时先读取分区，不能依赖后续 Consumer 创建 Topic。

## 在平台查消息与消费组

1. 在 **Topics** 搜索完整 Topic 名，核对集群、分区和配置；未找到时先检查环境与实际名称。
2. 进入 Topic 的 **Messages**，根据页面支持的时间、分区、offset 或内容筛选定位消息，再用 Key/业务标识确认。不要只看最新一屏；缩小了分区或扫描窗口后，无结果不代表整个 Topic 无消息。
3. 展开消息，核对 **Topic、Partition、Offset、Timestamp、Key、Headers、Value**。Topic、Partition、Offset 一起定位消息；时间相近或总数增加不能证明就是本次请求。
4. 按 Producer 的编码选择 Value 解码方式，按目标应用的规则核对 Headers。需要离线解码时获取原始 Value，具体导出格式与能力以页面为准，见下方解码方法。
5. 在 **Consumers / Consumer Groups** 打开实际组名，按 Topic 和 Partition 查看提交位点、末端位点、lag、活跃成员与分区分配，再关联目标服务日志及业务结果。

菜单名称、筛选作用范围和导出能力随部署版本变化，先读当前页面再操作。消息查询窗口、分区选择和消费组要互相对应，避免拿另一个组的 lag 解释当前消息。

## 使用 CLI 查询相同对象

本机 CLI 需要能访问 Broker 返回的 advertised 地址，并使用平台提供的客户端认证配置。Web 管理台可访问不能证明本机 Broker 网络或身份可用；转发一个 Broker 也不保证完整集群可达。

在已配置客户端的环境中，按需要选择命令：

```bash
# 使用本机安装的实际命令名；部分发行版不带 .sh。
kafka-topics.sh \
  --bootstrap-server '<Broker地址列表>' \
  --command-config '<客户端配置文件>' \
  --describe --topic '<实际Topic>'

kafka-consumer-groups.sh \
  --bootstrap-server '<Broker地址列表>' \
  --command-config '<客户端配置文件>' \
  --describe --group '<实际消费组>'

# 需要检查成员及分区分配时使用。
kafka-consumer-groups.sh \
  --bootstrap-server '<Broker地址列表>' \
  --command-config '<客户端配置文件>' \
  --describe --group '<实际消费组>' --members --verbose
```

命令选项按安装版本的 `--help` 或 [Kafka 操作说明](https://kafka.apache.org/41/operations/basic-kafka-operations/#managing-consumer-groups)核对。客户端配置应适配该工具的认证插件，不能直接传入应用 YAML。读取位点无需重置 offset，也不要启动同组临时 Consumer 查看消息，它会参与分区分配。

## 位点和消息分别能说明什么

| 观察 | 能得出的结论与下一步 |
|---|---|
| 没有活跃成员或分区分配 | 先查 Consumer 启动、连接与 rebalance |
| lag 持续增加 | 查处理耗时、失败重试与分区负载 |
| committed offset 越过目标消息 | 组的恢复位置已越过该消息；继续查业务处理结果 |
| lag 为 0 但结果缺失 | 核对是否查错组、路由过滤、失败后提交或业务另有重试 |
| 同一业务对象多条消息 | 比较消息轮次与业务幂等结果，区分重投与重复执行业务 |

位点按分区看。消息 offset 为 0、提交位点为 1，表示恢复位置越过该消息；lag 不是业务待办数，提交位点也不是业务成功标志。路由过滤、失败后提交等行为必须查当前 Consumer 实现，不能假定所有服务一致。

## 解码消息时保留原始字节

按同一业务标识关联消息的 Key、Headers、Partition、Offset 与业务记录。Value 显示乱码时先查编码格式；Protobuf 二进制不能按 JSON 或 String 判断是否损坏。

若 Producer 直接写入 Protobuf，可使用对应版本的正式协议解码：

```bash
buf convert . \
  --type '<完整消息类型>' \
  --from /tmp/event.bin#format=binpb \
  --to /tmp/event.json#format=json \
  --validate
```

输入必须是原始 Value 字节。Base64 导出先解码；带包装的导出先按格式提取 Value。不要把页面乱码复制后改后缀。`--validate` 会额外检查协议中的校验规则，校验失败与无法解码是不同问题。消息若只携带业务记录 ID，继续读取对应记录，不能仅因缺少业务字段判定消息不完整。

## 沿失败层继续查

| 卡点 | 检查 |
|---|---|
| 待发送记录一直未发出 | Dispatcher 是否运行、领取范围、租约、下次重试时间和发送错误 |
| 消息存在但目标版本不处理 | 实际 group、消息路由头、运行版本、业务记录执行范围 |
| 消费失败后没有后续动作 | handler 返回值、提交策略、重试耗尽行为与恢复任务 |
| 看见重复投递 | Producer 确认、Outbox 回执是否落库、恢复补发与业务幂等键 |

分开检查 Producer 重试、Consumer 本地重试和业务任务重试；一次消费重试不等于一次业务执行，重试预算不能跨层混算。

最终以同一业务对象的状态、持久化结果与读取接口判断完成。关联字段的选择见[业务链路日志](business-chain-logging.md)，存储检查见[数据库与 Redis 调试](database-debugging.md)。

## 创建、发送与调整位点

这些操作按本次明确任务单独处理，不能作为普通查看的附带步骤。

| 操作 | 先确定 | 操作后的判断 |
|---|---|---|
| 创建 Topic | 目标集群、实际名称、分区数、副本数和保留策略；项目已有资源管理入口 | 回读实际配置，并确认应用能取得元数据 |
| 发送或重放测试消息 | 编码、Key、Headers、目标消费范围、幂等行为和允许产生的业务效果 | 用准确消息身份关联消费及业务结果；手工发消息不能证明业务 Producer 已接通 |
| 重置消费位点 | 精确组、Topic、分区、目标位置与是否会重读或跳过数据；按工具要求处理活跃消费者，先预览变更范围 | 回读提交位点和恢复后的消费行为；重置不修复业务根因 |
