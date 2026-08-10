# 0025 Capability Truth Audit

- 状态：completed
- 创建日期：2026-08-08
- 完成日期：2026-08-08
- 范围：`mcp/education-resources` 的 Registry、Adapter/Inspector loader、Resolution/Representation、Policy、Acquisition、Plan/Job/Asset，以及 `skills/learning-resource-flow` 的能力语义
- 性质：只读架构审计；本轮不实施代码迁移，不改变现有运行行为

## 1. 审计结论

当前系统有三个相互重叠但没有完整闭合的“能力真相”来源：

1. **静态 Registry**：按平台声明 `search`、`browse_creator`、`inspect`、`acquire` 和一组粗粒度 acquisition strategy。
2. **运行时 Adapter/Provider map**：搜索和 Inspection 的内置注册，下载器通过可选导入注册；缺少下载器时会继续存在通用 direct provider。
3. **候选级 Inspection/Resolution 和实际 Job**：候选可产生 `representations`、`availability`、`materializable`、`rights_hint`，但没有 capability descriptor、provider readiness、scope 或权利资格的权威引用；Job/Asset 也没有 planned-vs-actual capability 记录。

因此：

- Registry 的 `acquire=true` 不能证明某个候选存在可下载的 primary 文件；平台级 strategy 不能推导候选级 Representation、provider、readiness 或 rights eligibility。
- `download_prepare` 当前只根据用户请求的 container 把所有资源映射为 `webpage` 或 `direct`，没有读取 fresh Resolution，也没有绑定候选级能力事实。
- `download_start` 只重新校验 token、Plan/Presentation/Selection 绑定和过期，不重新校验 readiness、eligibility、Representation/source 是否仍然匹配。
- Acquisition Router 在平台 provider 缺失时静默调用 generic direct provider；平台 provider 失败时还可能继续 generic fallback。这个 fallback 不能作为 Registry 声明能力的部署证明，也可能把不同 acquisition scope 混在一个结果里。
- Anna's Archive/Libgen 目前是“Libgen 搜索/元数据 + Anna landing URL + Libgen mirror 下载”混合路线。它能证明 metadata/landing/search 可用，不等于 concrete primary file 可用，更不等于有权下载；其下载 HTTP 也没有统一接入 shared URL policy。

**唯一推荐的 authority 链**：

```text
Static Capability Descriptor
  -> Deployment Readiness Snapshot
  -> Candidate-specific Resolution
  -> Representation + Resolved Capability
  -> Policy/Rights Eligibility
  -> per-resource download_prepare
  -> bound Plan + digest
  -> download_start revalidation
  -> Router/provider
  -> Actual Outcome + Asset/Bundle
  -> Skill explanation/archive
```

`capability descriptor`、`readiness`、`candidate resolution`、`eligibility`、`plan binding`、`actual outcome` 必须是服务端生成并可追溯的事实；模型只能对相关性、用途、适配性和用户解释作语义判断，不能伪造这些字段。

## 2. 代码证据地图

### 2.1 Static Registry 与 loader

| 证据 | 当前行为 | 缺口 |
| --- | --- | --- |
| `contracts/schemas/platform-registry.schema.json:7-29` | Registry 固定 `registry_version=1.0.0`，固定 16 个平台。 | 没有 capability descriptor ID/version/digest、scope、provider/inspector ID/version、readiness 或 fallback 前置条件。 |
| `.../platform-registry.schema.json:51-73` | 能力只有布尔 `search`、`browse_creator`、`inspect`、`acquire`。 | `acquire` 没有区分 primary resource、representation、landing page、metadata。 |
| `.../platform-registry.schema.json:110-131` | acquisition 只有 `webpage`、`platform_video`、`platform_audio`、`platform_resource`、`platform_book`。 | strategy 没有 provider、container/MIME、输入前置条件或 scope。 |
| `retrieval/registry.py:35-65,120-129` | validator 维护固定 16 平台、7 Inspection 平台和 specialized-strategy/platform 对照表。 | 这是硬编码集合一致性，不是当前部署 provider 的完整 truth。 |
| `retrieval/registry.py:399-433` | 只校验 search/inspection/acquisition 字段内部一致，且要求 `capabilities.acquire == bool(strategies)`。 | “声明了 strategy”被当成“可获取”，没有 import/load/readiness/rights 验证。 |
| `retrieval/registry.py:499-521` | 读取 schema 和 JSON 后深拷贝返回。 | loader 不接受运行时 provider map，也不产生 snapshot/digest/readiness。 |
| `adapters/base.py:81-166,183-203` | `AdapterDescriptor` 是 Registry entry 的不可变投影；`descriptor_for_platform()` 可按 platform 查找。 | Descriptor 仍只含 platform/resource/capabilities/identity/auth/source traits/strategies；没有 descriptor ID、部署版本、scope、provider/inspector 或策略版本。 |

### 2.2 Search/Inspection registration

| 证据 | 当前行为 | 缺口 |
| --- | --- | --- |
| `search.py:395-429` | 内置搜索 Adapter 逐个 `ImportError: pass`；成功实例化后以 `require_descriptor=True` 注册。 | 缺失模块可能只减少运行时 Adapter，Registry 仍声称平台存在；没有 readiness 记录或启动失败报告。 |
| `search.py:430-454` | 内置 Adapter descriptor 必须等于 Registry descriptor；legacy/third-party stub 仍可无 descriptor。 | 仅覆盖搜索注册，不能约束 acquisition provider。 |
| `inspection_registry.py:21-55` | 构造 7 个 Inspector，并 exact 比对 `INSPECTION_PLATFORM_IDS`；缺失/多余 Inspector 启动时报错。 | Inspection 有 exact consistency，acquisition 没有对应 provider/load/version/readiness 检查。 |

### 2.3 Candidate、Resolution、Representation 与 Inspection

| 证据 | 当前行为 | 缺口 |
| --- | --- | --- |
| `retrieval/models.py:201-250` | `Representation` 只记录 kind/container/MIME/role/language/estimated size/availability/materializable/requires_auth/`rights_hint`。 | 没有 capability ID/digest、provider/strategy、scope、readiness snapshot、evidence provenance/time、policy/rights decision。 |
| `retrieval/models.py:253-332` | Candidate 可带 `resolution_status` 和 representations。 | 搜索 Candidate 与具体 Resolution/capability 没有强引用关系。 |
| `retrieval/models.py:349-424` | Resolved resource 从 Candidate 复制 representations，并设置 `resolution_status=resolved`。 | “resolved”不保证 primary representation 可 materialize/download，也不保证 eligible。 |
| `contracts/schemas/tools/resource_inspect.schema.json:57-118` | Representation schema 允许 `materializable`、`requires_auth`、`rights_hint`。 | `availability`、`materializable` 和 rights_hint 的语义没有成为 action-specific eligibility。 |
| `contracts/schemas/tools/resource_inspect.schema.json:141-187,189-235` | Resolution 返回 resolved resource、representations 和 Inspector provenance/cache status。 | 没有 capability/readiness/eligibility 证据链。 |
| `storage.py:584-610,1280-1558` | `resource_resolutions` 持久化 profile/source fingerprint/status/resolved/inspection/failures。 | 缺少 capability/readiness/eligibility/evidence TTL 字段；旧 Resolution 不足以安全生成可执行下载计划。 |
| `service.py:461-520,2107-2161` | `resource_inspect` 可复用缓存；public output 只投影 Resolution/Inspection/failures；representation ID 可由服务端补齐。 | 只有 representation ID，不是 capability-aware reference；模型不得从缺失字段推断下载资格。 |

### 2.4 Prepare、Plan、Start

| 证据 | 当前行为 | 缺口 |
| --- | --- | --- |
| `service.py:648-721` | `download_prepare` 读取选择，按 requested container 推断 `webpage`（html/text/pdf）或 `direct`，建立 options/request hash/token。 | 不要求 fresh Resolution、exact Representation、provider readiness、candidate capability 或 rights eligibility。 |
| `contracts/schemas/tools/resource_download_prepare.schema.json:67-121` | Plan item 只有 resource_id、selected_position、platform、planned_container、size、max bytes、risks。 | 没有 representation_id、planned scope、descriptor/digest、provider、strategy、readiness、eligibility、fallback policy。 |
| `storage.py:2055-2212` | `create_plan` 只验证 current Presentation/Selection，按 resource id 生成 digest 和 Plan items；DB 只保存 resource IDs/options/token/digest/expiry。 | plan digest 不覆盖候选 capability/representation/scope/readiness/eligibility；每个 item 不是 exact acquisition binding。 |
| `service.py:742-830` | `download_start` 传给 `reserve_job` 的 bindings 是 presentation/selection/plan digest；只做控制面绑定和幂等。 | 没有 readiness TTL、eligibility expiry、representation/source/provider/descriptor revalidation。 |
| `storage.py:2398-2494` | `reserve_job` 校验 token/hash/plan used/expiry/selection digest/versions，然后创建 Job。 | 过期或被阻断的 provider/capability 仍可进入 Job。 |

### 2.5 Acquisition、Job、Asset

| 证据 | 当前行为 | 缺口 |
| --- | --- | --- |
| `service.py:1792-1818` | `_register_default_downloaders` 对 ximalaya/bilibili/smartedu/douyin/annas-archive 使用 `except ImportError: pass`。 | Registry 声明的 acquisition 能力可能静默缺失；没有 descriptor/provider version/readiness snapshot。 |
| `service.py:1820-1841` | `_acquisition_router_for_jobs` 将 platform downloader map 和 generic direct provider 注入 Router。 | Router 没有被 descriptor 约束；generic provider 使“无平台 provider”不显式失败。 |
| `acquisition/router.py:147-169` | 依据 Plan strategy 选择 direct/materialize/capture。 | strategy 不是候选级 capability binding。 |
| `acquisition/router.py:171-204` | platform provider 缺失时 `get(platform, direct_provider)`；平台 provider 失败时可安全 fallback 到 direct provider。 | fallback 可能改变 provider/semantic scope，且缺 provider 不会形成结构化 capability failure。 |
| `acquisition/router.py:292-369` | capture 可降级到 static materialization；materialization 不反向升级为 capture。 | fallback metadata 只有简单字符串，未记录 planned-vs-actual scope、provider chain、descriptor/readiness。 |
| `acquisition/models.py:277-327,349-420` | `AcquisitionStrategy.from_plan()` 支持旧 alias，缺 strategy 时按 resource type 保守推断。 | 缺 strategy 时仍可执行，绕过 candidate-specific Resolution；实际 provider 不在 request authority 中。 |
| `service.py:1843-2066` | Job 从 Plan options 生成 request，执行 Router，将 bundle/失败写入 AssetBundle；只有有 ready primary 才算可用。 | Job/Asset/Bundle 没有 planned scope、actual scope、representation、provider、fallback chain、readiness/eligibility outcome。 |
| `storage.py:202-224,653-714` | assets 持久化文件事实；asset_bundles/items/failures 持久化角色和完成度。 | 内容事实完整，但缺 acquisition authority/actual outcome 投影。 |
| `service.py:2163-2174` | public Asset 只返回 asset_id/resource_id/size/MIME/hash/validation/bundle relation。 | 用户无法区分 planned primary 与实际 landing/materialized/partial outcome。 |

### 2.6 Network/rights Policy 与 Anna/Libgen

| 证据 | 当前行为 | 缺口 |
| --- | --- | --- |
| `policy.py:38-308,389-439` | URL、host allowlist、DNS/SSRF、redirect、client path/root 校验。 | 没有 `candidate × representation × action` 的 rights/eligibility decision。 |
| `adapters/annas_archive.py:21-58` | 搜索用 Libgen，Candidate URL 写成 `https://annas-archive.gl/md5/<md5>`，metadata 中携带 MD5。 | Search/landing identity 与 concrete primary file locator 混合。 |
| `adapters/inspect_annas_archive.py:75-101,120-190` | 只允许有合法 MD5 的候选，通过 superclass 检查 Anna URL，再重写 document/primary representation；`materializable=false`、`requires_auth=false`、`rights_hint` 为 advisory。 | 没有 concrete file representation/provider/readiness/eligibility；`role=primary` 容易被误读为已可下载 primary。 |
| `adapters/libgen_client.py:87-124,288-348` | mirrors 可从 `ANNA_LIBGEN_MIRRORS` 环境变量覆盖；普通 `urlopen_with_fallback` 访问 `/ads.php`、`get.php`，下载只做取消、max_bytes。 | 未统一使用 `validate_public_http_url`；host allowlist、逐跳 redirect、content type/真实格式校验缺失。 |
| `adapters/libgen_client.py:377-390` | 默认 mirrors 为 `https://libgen.bz`、`https://libgen.gl`。 | 环境变量可扩大边界，必须服务端 allowlist/SSRF/policy 约束。 |

### 2.7 Skill/契约语义漂移

| 证据 | 当前行为 | 缺口 |
| --- | --- | --- |
| `skills/learning-resource-flow/references/platform-capabilities.md` | 已说明 `acquire=true` 不等于质量、可下载、版权授权。 | 服务端 `download_prepare` 仍无候选级 gate，文档提醒未变成执行权威。 |
| `skills/learning-resource-flow/references/acquisition-strategy.md:48-67` | 要求 direct file 由 Inspection/source fact 证明；webpage/materialize/capture 有明确 scope。 | Service 当前按 container 直接选 strategy，未要求这些 facts。 |
| `skills/learning-resource-flow/references/inspection-strategy.md:27-61,91-129` | 要求下载前判断 Representation，只能依据 Resolution/Inspection 事实。 | `download_prepare` 不实际读取/绑定 Resolution，Skill 规则高于服务端真相。 |
| `contracts/domain-contract.md:139-167,207-223` | 文档要求精确 Inspection router、Plan revalidation 和 representation-aware download。 | Plan schema/storage 与文档不一致。 |

## 3. 唯一最优领域模型

### 3.1 Static Capability Descriptor

Registry 保留为静态输入，但 authority 迁移为按以下笛卡尔积定义的 descriptor：

```text
platform × resource_type × scope × representation × strategy
```

建议字段：

```json
{
  "capability_id": "cap_annas_book_primary_direct_pdf",
  "descriptor_version": "2.0.0",
  "platform_id": "annas-archive",
  "resource_types": ["book", "document"],
  "scope": "primary_resource",
  "representation": {
    "kind": "document",
    "container": "pdf",
    "mime_types": ["application/pdf"],
    "role": "primary"
  },
  "strategy": "direct_file",
  "provider": {"provider_id": "annas-libgen", "version": "..."},
  "inspector": {"inspector_id": "annas_archive", "version": "..."},
  "prerequisites": {"required_fields": ["md5"], "auth_mode": "none"},
  "policy_class": "public_metadata_and_file",
  "fallback": {"allowed": true, "max_scope": "representation"}
}
```

必填字段至少包括：

- `capability_id`、`descriptor_version`、descriptor canonical digest；
- `platform_id`、`resource_types`；
- `scope`：`primary_resource`、`representation`、`landing_page`、`metadata`；
- representation kind/container/MIME/role；
- acquisition strategy；
- provider ID/version、inspector ID/version；
- auth/prerequisites、policy class/domain rules；
- fallback policy（允许的失败码、scope-preserving/lowering 约束）。

现有 `capabilities.acquire` 与 `acquisition.strategies` 只能保留为 deprecated compatibility metadata，不再作为执行 authority。

### 3.2 Deployment Readiness Snapshot

每个 descriptor 在当前进程/部署中生成受服务端保护的 readiness snapshot：

```json
{
  "snapshot_id": "ready_...",
  "capability_id": "...",
  "descriptor_digest": "sha256:...",
  "status": "ready",
  "provider_id": "annas-libgen",
  "provider_version": "...",
  "load_status": "loaded",
  "constructor_status": "ok",
  "credential_posture": "none",
  "network_policy_status": "ok",
  "failure_code": null,
  "observed_at": "...",
  "expires_at": "...",
  "snapshot_digest": "sha256:..."
}
```

`status` 至少允许：`ready`、`degraded`、`blocked`、`experimental`、`unsupported`。启动时：

- Registry descriptor、provider map、inspector map 必须 exact consistency；
- import/constructor/version/policy failure 形成结构化 readiness failure；
- readiness 未通过不得静默使用 generic provider；
- TTL 过期必须使 prepare/start 重新 resolve 或失败。

### 3.3 Candidate-specific Resolution / Representation

`Resolution` 与每一项 `Representation` 必须携带服务端 authority 引用：

```json
{
  "resource_id": "res_...",
  "resolution_id": "resolve_...",
  "representation_id": "repr_...",
  "scope": "primary_resource",
  "capability": {
    "capability_id": "...",
    "descriptor_digest": "sha256:...",
    "provider_id": "...",
    "strategy": "direct_file",
    "readiness_snapshot_id": "ready_..."
  },
  "technical_availability": "available",
  "evidence": {
    "source": "inspection",
    "source_url_fingerprint": "sha256:...",
    "observed_at": "...",
    "expires_at": "..."
  }
}
```

`technical_availability` 只说明技术事实。平台“支持图书”不能推导某条候选存在 concrete primary file。`rights_hint` 继续作为 advisory 用户提示，不得转换成资格。

### 3.4 独立 Eligibility Decision

建立独立决策实体：

```text
candidate × representation × action
```

`action` 至少有 `inspect`、`materialize`、`download`、`archive`；状态至少有：

- `eligible`
- `ineligible`
- `unknown`
- `auth_required`
- `policy_blocked`
- `manual_review`

记录 `decision_id`、rule/policy version、rule ID、reason、evidence timestamp、expiry；`rights_hint` 不可覆盖该实体。

### 3.5 PlanItem / ActualOutcome

`download_prepare` 生成 exact per-resource item，至少绑定：

- `resource_id`、`representation_id`；
- `planned_scope`、platform、provider、strategy；
- descriptor ID/digest、readiness snapshot ID；
- eligibility decision ID/status/expiry；
- requested/planned container、max bytes；
- explicit fallback policy；
- item digest（并纳入整体 `plan_digest`）。

Job/AssetBundle 持久化 `ActualOutcome`：

- planned scope vs actual scope；
- actual representation/provider/strategy；
- fallback chain（每步 provider/strategy/scope/reason）；
- status、failure/partial details；
- final asset/bundle relation。

Scope 只允许保持或降低：

```text
primary_resource > representation > landing_page > metadata
```

fallback 不能升级 scope；browser/materializer 结果不能被报告为 primary book/video；Anna/Libgen concrete file route 失败时只能返回 landing/metadata/partial outcome，不得虚构 primary。

## 4. 逐文件迁移方案

### Phase A — Contracts/Registry/Loader

1. 新增 `contracts/schemas/capability-descriptor.schema.json`、`deployment-readiness.schema.json`、`eligibility-decision.schema.json`、`actual-outcome.schema.json`；在 `common.schema.json` 增加 ID/digest/scope/status enums。
2. 新增 `contracts/capabilities/`（或同等目录）静态 descriptor catalog，替换 Registry 中“acquire + strategies”作为 authority 的角色。
3. `contracts/schemas/platform-registry.schema.json` 与 `platform-registry.json` 保留旧字段但标注 deprecated；catalog/contract version 递增。旧 registry 不得自动推导新的 primary capability。
4. `retrieval/registry.py` 增加 descriptor loader、canonical digest、provider/inspector binding 和 exact consistency validator；输出 registry + descriptor snapshot，不接受模型提交。
5. `adapters/base.py` 扩充 `AdapterDescriptor` 只读字段（ID/version/scope/provider/inspector/prerequisites/policy）；`descriptor_for_platform` 仅作为兼容查找，执行时使用 capability ID。

### Phase B — Runtime readiness

1. 新增 `capability_readiness.py`（或放入 retrieval/registry）注册 provider/inspector factory、版本和 policy probe。
2. `search.py`、`inspection_registry.py`、`service._register_default_downloaders()` 统一通过 readiness registry；内置 importer/constructor 失败必须形成 `blocked`/`unsupported` snapshot，禁止 `except ImportError: pass` 后继续声明 ready。
3. `ResourceService` 启动或首次使用时生成 snapshot，记录 observed/expiry；generic provider 只可挂到显式 generic descriptor，不可接管缺失的 platform capability。

### Phase C — Resolution/Policy

1. `retrieval/models.py` 新增 `CapabilityRef`、`EvidenceRef`、`ResolvedRepresentation`、`EligibilityDecision`；保留 `Representation.rights_hint` 兼容读取但标记 advisory。
2. `resource_inspect` schema 把 capability/readiness/evidence/eligibility 作为返回字段；`storage.resource_resolutions` 增加 JSON 或规范化列，缓存 key 必须包含 descriptor digest/provider version/policy version。
3. `policy.py` 增加 `evaluate_eligibility(resource_id, representation_id, action, context)`，与网络 SSRF/path policy 分开；公开技术 Network policy 不得假装 rights decision。
4. Inspector 必须在写 Resolution 前选择/记录候选级 representation scope；无 concrete file evidence 只能写 landing/metadata representation。

### Phase D — Prepare/Plan/Start

1. `service.download_prepare()` 对每个 selected resource 读取 fresh/cached Resolution，选择 exact Representation；检查 descriptor、readiness 和 `download` eligibility。
2. 无 `ready + eligible + primary` 时：默认失败并返回结构化 reason；只有用户/Skill 明确要求探索时才允许显式降级到 landing/metadata，并在 Plan item 中写明 scope，不得伪装可下载 primary。
3. 扩充 `resource_download_prepare.schema.json` PlanItem；`storage.download_plans` 增加 `items_json`/capability references（或规范化子表）；plan digest 覆盖所有绑定字段。
4. `download_start()` 和 `storage.reserve_job()` 除现有 token/selection/expiry 外，重新验证 readiness TTL、eligibility expiry、descriptor/provider version、representation/source fingerprint、scope 和 fallback policy。
5. 旧 Plan：仅兼容读取/诊断；所有缺少 capability-aware bindings 的旧 Plan 立即失效，不迁移为可执行状态。

### Phase E — Router/Job/Asset

1. `AcquisitionRequest` 由 PlanItem 构造，必须携带 capability ID/digest、representation ID、planned scope、provider ID、readiness snapshot、eligibility ID。
2. `AcquisitionRouter` 只从 descriptor 绑定的 provider 取实现；provider missing/blocked 返回 `CAPABILITY_NOT_READY` 或稳定结构化失败。
3. 删除生产路径的静默 generic direct fallback；保留 legacy injected provider 仅用于测试/兼容 seam，并要求显式 descriptor/flag。
4. fallback 必须返回 `FallbackStep`，验证 scope 不升级；在 `ActualOutcome` 中记录 planned-vs-actual、provider chain、strategy、representation、reason。
5. `storage.jobs/assets/asset_bundles` 增加 outcome JSON/规范化字段；`resource_job_status`、`flow_status`、Asset public projection 返回 scope/actual outcome，避免把 landing/materialized 报告成 primary。

### Phase F — Anna/Libgen 与 Skill

1. 将 Anna/Libgen descriptor 拆为 `metadata/landing` 与 concrete file capability；没有实际文件 locator/格式/大小/内容证据时，不生成 primary file capability。
2. `libgen_client.py` 所有 mirror、redirect、download URL 统一通过 `validate_public_http_url`，固定 allowlist；禁止环境变量扩大到未批准 host；补 content-type/真实文件格式/size/redirect/cancel/idempotency 检验。
3. `inspect_annas_archive.py` 把 `rights_hint` 继续作为提示；把 `materializable=false` + concrete file absence 解释为 no primary capability，不再使用 `role=primary` 暗示可下载。
4. 更新 `platform-capabilities.md`、`acquisition-strategy.md`、`inspection-strategy.md`、`mcp-workflow.md`、`candidate-judgment.md` 和 `contracts/compatibility.md`，明确服务端 gate 高于 Skill 文档推断。

## 5. 兼容边界

保留：

- `flow_id`、`resource_id`、`resolution_id`、`representation_id`、`plan_id`、`job_id`、`asset_id` 的服务端 opaque ID 语义；
- `prepare -> 用户确认 -> start` 两阶段副作用边界、幂等键和 Plan digest 绑定；
- 旧 Registry 的 search/inspect metadata 作为只读 compatibility input；
- `capabilities.acquire`、`acquisition.strategies`、`Representation.rights_hint` 旧字段可读，但全部 deprecated/advisory，不可作为执行 authority；
- legacy/third-party provider 测试 seam，但必须显式注入并声明 compat mode，不能影响 production readiness truth；
- 单文件 `DownloadResult` 到 singleton primary Bundle 的内容兼容，只能在 capability-aware PlanItem 下执行。

不兼容/立即失效：

- 任何没有 exact representation/capability/readiness/eligibility 的旧 Plan 不得继续 start；
- 任意模型提供的 provider ID、strategy、scope、readiness、eligibility、asset path、locator 不被信任；
- generic direct fallback 不得掩盖缺失的 platform provider；
- `rights_hint`、`requires_auth=false`、`materializable=true` 不得自动产生 download/archive eligibility；
- landing/metadata 能力不得提升为 primary resource/primary file；
- fallback 不能提高 scope，不能把 browser capture/static materialization 伪装为原始视频/图书文件。

## 6. 测试矩阵

| 层 | 必测场景 | 期望 |
| --- | --- | --- |
| Registry/schema | descriptor 字段、canonical digest、未知字段、旧 acquire/strategy 兼容读取 | schema 拒绝越权/凭据/路径；旧字段不再产生 capability authority |
| Registry↔runtime | provider/inspector 缺失、导入异常、constructor 异常、版本不匹配、descriptor mismatch、readiness TTL/degraded/blocked | 启动/首次使用产生结构化 readiness；不能静默 generic fallback |
| Search/Inspection | adapter map exact set、candidate-specific Representation、fresh/cached source fingerprint、旧 Resolution | 每个 Resolution 带 capability/readiness/evidence；缓存命中不能越过 expiry/version |
| Eligibility | `rights_hint` 仅 advisory；`inspect/materialize/download/archive` 各 action；unknown/auth/policy/manual_review | 无 eligible 不得 prepare；过期 decision 使 prepare/start 失败 |
| Prepare/Plan | 未 inspect、无 Representation、无 primary、container mismatch、scope 降级、items 绑定 | per-resource gate；Plan item 完整；digest 覆盖 provider/representation/scope/readiness/policy |
| Start | token、plan/selection digest、readiness/eligibility expiry、source/descriptor drift、重复幂等 | stale/changed state 结构化拒绝；不会创建不可执行 Job |
| Router | missing provider、provider failure、explicit fallback、fallback chain、scope upgrade attempt、capture/materialize distinction | missing provider = capability failure；fallback 只保持/降低 scope且可见 |
| Job/Asset | actual provider/strategy/representation、planned-vs-actual、partial/failed、primary invariant、cancel/retry | Asset/Bundle 保留内容与获取 outcome；不把 landing 报成 primary |
| Anna/Libgen | 搜索成功但 concrete download 不可用、landing-only、镜像 allowlist、SSRF/private DNS、redirect、大小、content-type/真实格式、取消/幂等 | metadata/landing 可保留；无文件证据不生成 primary capability；非法镜像拒绝 |
| Contract/docs | tool catalog、Schema、compatibility、Markdown links、`git diff --check`、stdio/OpenClaw probe | 版本和文档与 runtime 一致；probe diagnostics=[] |
| Calibration | 标题相关但无正文证据、Inspection 不相关、错误 resource_target、hard constraint unknown/conflict、不同比较/来源族、教材同步最小澄清、连续零增益、AUTH/POLICY/FEATURE_NOT_SUPPORTED、representation 不确定 | Skill semantic review 与服务端 factual capability 分离；StopDecision 唯一且可解释 |

## 7. 明确拒绝方案（不可作为修复）

- **拒绝把 Registry `acquire=true` 继续当下载 authority**：它没有候选、表示形态、provider、readiness 或 rights 维度。
- **拒绝仅给 `Representation` 增加 `materializable=true`/`requires_auth=false`**：这仍不是 action-specific eligibility，也不能证明文件主体、授权或内容格式。
- **拒绝只在 Skill 文档中提醒“先 Inspection”**：服务端 `download_prepare` 必须自己 gate；模型提示不是安全边界。
- **拒绝缺 provider 时继续 generic direct fallback**：这会把部署缺失伪装成能力，且可能跨 scope。
- **拒绝通过更长 timeout、吞掉 ImportError、扩大 mirror 列表来“修复” readiness**：这只掩盖配置/部署事实。
- **拒绝把 Anna landing、Libgen metadata 或 MD5 当成 concrete primary file 证据**：需要实际 representation/provider/readiness/eligibility 证据。
- **拒绝让模型提交任意本地路径、下载 URL、provider 状态、job/asset 状态**：所有业务状态必须由 MCP 服务端生成。
- **拒绝用一次全局平台判定替代 candidate × representation × action**：同一平台不同候选、版本、格式和访问状态可以不同。
- **拒绝将 browser capture/materializer fallback 报告为原始 primary video/book**：fallback scope 必须显式降低或保持。

## 8. 本轮验证与剩余风险

- 本轮只读，未修改工作区（除新增本审计计划文件作为交付文档）。
- 已通过源码、Schema、契约和 Skill reference 的静态交叉审计；未运行测试、OpenClaw probe 或真实平台网络访问。
- 剩余风险：当前分支有其他任务的未提交 README/docs/plan 修改；实施 0025 时必须保留这些修改，不得 reset/checkout/宽范围格式化。真实 provider readiness、rights policy 和 Anna/Libgen 网络安全迁移尚未实现。
- 后续实施顺序按第 4 节 Phase A→F；先做 descriptor/readiness/policy/eligibility 契约和定向回归，再改 Plan/Router/Job，最后处理真实平台和 Skill/compat 文档。
