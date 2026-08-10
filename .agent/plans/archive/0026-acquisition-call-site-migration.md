# Acquisition authority call-site migration

- 状态：completed
- 创建日期：2026-08-08
- 完成日期：2026-08-08
- 范围：`mcp/education-resources/tests` 中非 `service.py` 的 Acquisition Router/Request 调用点

## 步骤

- [x] completed：盘点现有调用点与服务端计划产生的 authority/provider 绑定。
- [x] completed：将直接 WebMaterializer 请求补齐不可伪造的 authority 字段，并明确为 `landing_page` 物化。
- [x] completed：将服务级测试和 stdio fixture 的 Router 构造改为 exact `ProviderRegistration`；不保留隐式 direct/platform/browser fallback。
- [x] completed：为服务级测试提供离线 Inspector、在 prepare 前持久化 Resolution，运行定向测试、编译和 diff 检查，并记录 service-owner 集成状态。

## 验证

- `PYTHONPATH=tests python3 -m unittest -v test_web_materializer`：13/13 通过。
- `PYTHONPATH=tests python3 -m unittest -v test_acquisition_service test_asset_bundle_service test_rendering_download`：9 个底层 materializer/rendering/CDP 测试通过；5 个服务级测试均在 `ResourceService.download_prepare()` 进入 `Store._normalize_plan_capability_items()` 时失败，错误一致为 `ValueError: capability_binding_missing`。
- `python3 -m py_compile`：本次五个测试/fixture 文件通过。
- `git diff --check`：通过。
- Router 旧关键字构造盘点：除 `service.py` 外无 `direct_provider`、`platform_providers`、`web_materializer` 或 `browser_capture` 关键字构造残留。

## 结果

- Generic verified primary 测试绑定为 `generic-direct@1.0.0` / `direct_file` / `primary_resource`；网页物化绑定为 `generic-web-materializer@1.0.0` / `web_materialize` / `landing_page`。
- `test_web_materializer.py` 的直接请求带齐 provider、scope、representation、binding/source fingerprint、descriptor/readiness/eligibility authority 字段，且 scope 为 `landing_page`。
- 三个服务级测试均在 search 后、presentation/prepare 前调用离线 `service.inspect()`，因此不再依赖默认或网络 Inspector。
- `stdio_e2e_fixture_server.py` 明确声明视频、图书和课程主资源的 `primary_resource` scope；文章声明 `landing_page` + `landing` role；课程附件声明 `representation`。
- 剩余集成依赖：`service.py` 当前尚未向 `Store.create_plan()` 生成并传入 authority-bound `capability_items`，所以上述 5 个服务级测试在 prepare 阶段无法完成。此项属于 service owner 范围，未在本次任务中绕过或修改。
