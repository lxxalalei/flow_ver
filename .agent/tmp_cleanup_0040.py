from pathlib import Path
import re

ROOT = Path('.')
SRC = ROOT / 'mcp/education-resources/src/education_resource_mcp'
TESTS = ROOT / 'mcp/education-resources/tests'


def replace_exact(path: Path, old: str, new: str, *, count: int | None = None) -> None:
    text = path.read_text(encoding='utf-8')
    actual = text.count(old)
    expected = actual if count is None else count
    if count is not None and actual != count:
        raise SystemExit(f'{path}: expected {count} occurrences, found {actual}: {old!r}')
    if actual == 0:
        raise SystemExit(f'{path}: pattern not found: {old!r}')
    path.write_text(text.replace(old, new), encoding='utf-8')


# 1) Internal naming: acquisition scope/route, not Capability Authority.
for base in (SRC, TESTS):
    for path in base.rglob('*.py'):
        text = path.read_text(encoding='utf-8')
        updated = text.replace('CAPABILITY_SCOPES', 'ACQUISITION_SCOPES')
        updated = updated.replace('CapabilityScope', 'AcquisitionScope')
        if updated != text:
            path.write_text(updated, encoding='utf-8')

for rel in (
    'acquisition/router.py',
    'acquisition/simple.py',
):
    path = SRC / rel
    text = path.read_text(encoding='utf-8')
    text = text.replace('_AUTHORITY_METADATA_KEYS', '_ROUTE_METADATA_KEYS')
    text = text.replace('_authority_kwargs', '_route_kwargs')
    text = text.replace('_without_authority_metadata', '_without_route_metadata')
    text = text.replace('router authority facts', 'router route facts')
    text = text.replace('authority-bound request', 'route-bound request')
    text = text.replace('capability scope', 'acquisition scope')
    text = text.replace('capability scopes', 'acquisition scopes')
    path.write_text(text, encoding='utf-8')

# 2) ResourceService: remove dead capability constructor arg and make optional
# provider init failures visible without logging sensitive exception text.
service = SRC / 'service.py'
text = service.read_text(encoding='utf-8')
if 'import logging\n' not in text:
    text = text.replace('import json\n', 'import json\nimport logging\n', 1)
if 'LOGGER = logging.getLogger(__name__)' not in text:
    text = text.replace(
        '\n\nTERMINAL_JOB_STATES =',
        '\n\nLOGGER = logging.getLogger(__name__)\n\nTERMINAL_JOB_STATES =',
        1,
    )
text = text.replace('        capability_registry_snapshot: Any | None = None,\n', '')
text = text.replace('        del capability_registry_snapshot\n', '')
segment_start = text.index('        if acquisition_router is None:')
segment_end = text.index('            self.acquisition_router = AcquisitionRouter(registrations)', segment_start)
segment = text[segment_start:segment_end]
needle = '            except Exception:\n                pass\n'
provider_ids = (
    'smartedu-resource',
    'douyin-video',
    'ximalaya-audio',
    'bilibili-video',
)
if segment.count(needle) != len(provider_ids):
    raise SystemExit(
        f'service.py: expected {len(provider_ids)} silent provider init catches, found {segment.count(needle)}'
    )
for provider_id in provider_ids:
    replacement = (
        '            except Exception as exc:  # optional provider plugin boundary\n'
        f'                LOGGER.warning("Provider {provider_id} unavailable during initialization (%s)", type(exc).__name__)\n'
    )
    segment = segment.replace(needle, replacement, 1)
text = text[:segment_start] + segment + text[segment_end:]
service.write_text(text, encoding='utf-8')

# 3) Remove unreachable copy/paste residue from Store helper.
storage = SRC / 'storage.py'
text = storage.read_text(encoding='utf-8')
dead = '''    return text\n    if value is None:\n        return default\n    return json.loads(value)\n'''
if text.count(dead) != 1:
    raise SystemExit(f'storage.py: expected one unreachable helper tail, found {text.count(dead)}')
text = text.replace(dead, '    return text\n', 1)
storage.write_text(text, encoding='utf-8')

# 4) Current-plan/document cleanup.
plan39 = ROOT / '.agent/plans/0039-download-platform-active-expansion.md'
text = plan39.read_text(encoding='utf-8')
text = text.replace('`mcp/education-resources/src/education_resource_mcp/simple_service.py`', '`mcp/education-resources/src/education_resource_mcp/service.py`')
text = text.replace('`simple_service.py`', '`service.py`')
text = text.replace('`simple_storage.py`', '`storage.py`')
plan39.write_text(text, encoding='utf-8')

plan28 = ROOT / '.agent/plans/0028-real-openclaw-platform-e2e.md'
text = plan28.read_text(encoding='utf-8')
old_result = 'SmartEdu 工程实现已同步安装到 Windows education-resources 包，但用户尚未执行真实平台测试。\nDouyin、Ximalaya 和 Bilibili 的 active route 仍由 0039 继续实现。本计划不把任何离线验证解释为真实平台通过。'
new_result = 'SmartEdu、Douyin、Ximalaya、Bilibili 的 active exact route 均已完成工程接入；用户尚未执行真实平台验收。\n0039 当前只根据用户真实测试反馈修复平台问题。本计划不把任何离线验证解释为真实平台通过。'
if old_result not in text:
    raise SystemExit('0028 current result shape changed')
plan28.write_text(text.replace(old_result, new_result, 1), encoding='utf-8')

plan37 = ROOT / '.agent/plans/archive/0037-acquisition-state-simplification.md'
text = plan37.read_text(encoding='utf-8')
text = text.replace('- 状态：in_progress\n', '- 状态：completed\n', 1)
text = text.replace('- 完成日期：未完成\n', '- 完成日期：2026-08-12\n', 1)
text = text.replace(
    '- 接替关系：0036 已 superseded 并移入 archive；平台恢复目标后续继续，但不得恢复旧 Capability Authority 链\n',
    '- 接替关系：0036 已 superseded；0037 工程简化已完成并归档，真实 OpenClaw/平台验收移交 0028\n',
    1,
)
text = text.replace('simple_service.ResourceService', 'service.ResourceService')
text = text.replace('simple_storage.Store (migration 9)', 'storage.Store (migration 9)')
text = text.replace('`simple_service` / `simple_storage`', '`service` / `storage`')
text = text.replace('Active `simple_service`', 'Active `service`')
# The archived plan must not claim an unperformed real-user validation is still
# part of its own completion gate after ownership moved to 0028.
remaining_start = text.find('## Remaining work\n')
checkpoint_start = text.find('## Milestone checkpoint\n')
if remaining_start != -1 and checkpoint_start != -1 and remaining_start < checkpoint_start:
    replacement = '''## Remaining work\n\n0037 的工程范围已完成并归档。真实 OpenClaw / 平台用户验收不再作为 0037 的完成条件，统一由 0028 记录。\n\n'''
    text = text[:remaining_start] + replacement + text[checkpoint_start:]
text = text.replace('Actual user flow validated?: offline MCP yes; real OpenClaw pending', 'Actual user flow validated?: offline MCP yes; real OpenClaw transferred to 0028')
text = text.replace('[ ] real Agent/user-flow revalidated\n', '')
completion_start = text.find('## Completion condition\n')
if completion_start != -1:
    text = text[:completion_start] + '''## Completion condition\n\n已完成：Active acquisition 不再依赖旧 Capability Authority 状态链，migration 9 与 current contract cleanup 已落地，离线 MCP 业务闭环通过。真实 OpenClaw / 平台验收由 0028 继续。\n'''
plan37.write_text(text, encoding='utf-8')

# 5) Guardrails: do not reintroduce removed authority runtime identifiers.
for forbidden in ('authority_digest', 'readiness_snapshot_id', 'eligibility_id'):
    hits = []
    for path in SRC.rglob('*.py'):
        data = path.read_text(encoding='utf-8')
        if forbidden in data:
            hits.append(str(path))
    if hits:
        raise SystemExit(f'forbidden active authority identifier {forbidden}: {hits}')

print('cleanup patch applied')
