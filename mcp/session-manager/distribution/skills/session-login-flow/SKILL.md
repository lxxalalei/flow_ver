---
name: session-login-flow
description: Guide OpenClaw users through platform session checks, browser login/capture, explicitly authorized canonical Cookie/Token direct import, minimal persistence, validation, re-login, and deletion. Never request or autofill accounts, passwords, CAPTCHA, SMS codes, or MFA, and never narrate or echo session values.
---

# Session Login Flow

Use `session-manager` as the authority for platform metadata, extraction rules, saved state, and secure
persistence. The MCP cannot operate the browser; this Skill coordinates the host browser with it.

## Required capabilities

- Status: `resource_session_status`
- Login/capture/save: status + `resource_session_login_guide` + `resource_session_save`
- Re-login/delete: also `resource_session_delete`
- Browser: open URLs, read the controlled browser context's cookies, read the active official
  origin's `localStorage` and `sessionStorage`, and report the active URL/origin

If a required browser or MCP capability is unavailable, explain the limitation and stop that
mutation. A read-only status check may still proceed.

## Check and open login

1. Call `resource_session_status` for the requested platform(s). Use `deep=true` only when the user
   asks whether an existing session really works.
2. Treat `not_required` as public access. Treat `stored` as local structure only; only
   `probe_status=valid` is remote confirmation. Normalize an omitted probe result to
   `probe_status=no_probe` in the explanation.
3. Unless the user already satisfies the explicit direct-import branch below, call
   `resource_session_login_guide` for each platform needing login. Its `login_url` and
   `probe_supported` are authoritative. `cookie_domains`, `storage_keys`, and
   `storage_key_patterns` are **server extraction hints, not browser-side capture allowlists**.
4. Open `login_url`. Tell the user to finish login in that OpenClaw-controlled browser and reply
   exactly **“已登录”**. End the turn and wait. Do not replace this gate with a timeout, URL change,
   page text, Cookie observation, or an ambiguous reply such as “好了”.
5. Never ask for, accept, paste, or type a username, password, CAPTCHA, SMS/authenticator code, QR
   content, or MFA. The only non-browser exception is the explicit direct-import branch below.

## Explicit canonical direct import

Use this branch only when the user voluntarily provides a legally obtained Cookie/Token, names one
supported platform and authentication purpose, and explicitly authorizes local saving. Do not solicit
the value. Check status/platform support, generate one unique `idempotency_key`, and send the canonical
value once only as `resource_session_save.session_data`.

- Accept only existing canonical `cookies` or platform `tokens` shapes; never accept arbitrary headers,
  files, browser profiles, passwords, CAPTCHA/MFA material, or guessed/transformed fields.
- Never combine direct import with browser capture. Never reproduce the value in narration, screenshots,
  logs, temporary files, plans, or any non-save tool call.
- If save fails, times out, or its response is uncertain, do not replay it or ask the user to resend.
  Read authoritative status without the value, stop, and require fresh explicit authorization for any
  later write.
- After save, report only status/count/revision metadata. `stored/no_probe` is local evidence only;
  downstream platform Search/Inspect must still prove that the session works.

## Capture after “已登录”

Only continue after the explicit confirmation.

1. Verify the active tab is on the expected platform. Match the normalized hostname by DNS label
   boundary against the login host or returned `cookie_domains`; never accept a raw suffix such as
   `evilsmartedu.cn`. If unrelated, reopen the official URL, require a new “已登录”, and stop.
2. Read **all cookies the controlled browser cookie capability returns** for its current browser
   context. Do not prefilter names or domains in the Agent. Browser-specific metadata may remain in
   the submitted Cookie objects; the MCP removes it.
3. If `capture_method=browser_storage`, also read every key/value currently visible in the active
   official page's `localStorage` and `sessionStorage`. Record `location.origin` as
   `storage_origin`. Do not parse SmartEdu dynamic keys or JSON in the Skill.
4. Send one immediate `resource_session_save` call:

   Cookie flow:

   ```json
   {
     "cookies": ["<browser cookie objects; values omitted here>"]
   }
   ```

   Cookie + storage flow:

   ```json
   {
     "cookies": ["<browser cookie objects; values omitted here>"],
     "storage_origin": "https://official-origin.example",
     "local_storage": {"<browser key>": "<browser value>"},
     "session_storage": {"<browser key>": "<browser value>"}
   }
   ```

   Examples are structural placeholders only. Never put real captured values in chat, narration,
   screenshots, logs, temporary files, or any non-save tool call.
5. Generate a unique `idempotency_key`. Reuse it only after establishing that a retry is safe and uses
   the exact same browser capture; never automatically replay an uncertain write.
   The MCP fingerprints the minimized result, so unrelated browser-state noise may change safely.
   Omit `expires_at` unless one reliable expiry applies to the complete platform session.
6. The MCP may receive broad browser data, but it must apply platform-specific domain/key/pattern
   checks and persist only the canonical minimum. For SmartEdu it can recognize the constrained
   dynamic `ND_UC_AUTH-...&ncet-xedu&token` storage record, parse its JSON, and normalize the required
   nested token without preserving the raw storage dump.
7. Call status again using `deep=true` only when `probe_supported=true`. Report only platform,
   local status, capture/expiry metadata, stored/discarded counts, and probe result. Never reproduce
   `session_data`.

## Multiple platforms

When the user requested several platforms, keep an in-conversation pending list from the initial
status result. After one platform saves and its status check completes, automatically open the next
missing platform and ask for “已登录”; no extra permission is needed. Each platform still has its own
mandatory confirmation gate. Stop after one failed capture or one invalid post-save probe instead of
looping indefinitely.

## Credential boundary and secure storage

Raw browser values currently pass through Agent/MCP tool arguments. Keep them out of narration and
all other calls, but do not claim model/tool-channel isolation. Stronger isolation requires a future
host Plugin that returns an opaque `capture_id`.

At rest, the MCP owns protection. A natively running Windows MCP uses current-user DPAPI; a WSL MCP
uses the POSIX backend even when OpenClaw itself runs on Windows. Never downgrade to plaintext when
`SECURE_STORAGE_UNAVAILABLE` is returned.

## Re-login, delete, and failures

- Re-login: delete the platform session with a new idempotency key, then run the login flow.
- Delete only: delete that platform only; never reset the whole browser profile.
- `SESSION_EMPTY`: for browser capture, keep/reopen the official tab, ask the user to complete remaining
  redirect or consent, then allow one fresh capture. Do not solicit manual Cookie export. For direct
  import, stop without replaying or asking the user to resend.
- `SESSION_PAYLOAD_INVALID`: never print the submitted item. For browser capture only, reopen the
  official page and retry once; persistent failure means the extractor or capture shape needs updating.
  For direct import, read status and stop without replaying or asking the user to resend; any later write
  requires fresh explicit authorization.
- `SECURE_STORAGE_UNAVAILABLE`: stop immediately; do not recapture, probe, or write plaintext.
- `probe_status=invalid`: offer one clean re-login unless already authorized; never auto-loop.
- `probe_status=probe_error`: preserve the saved record and report inconclusive verification.
- CAPTCHA, QR, device confirmation, and MFA are completed only by the user in the browser.

For exact turn boundaries, payload shapes, status semantics, and recovery rules, read
[references/login-workflow.md](references/login-workflow.md).
