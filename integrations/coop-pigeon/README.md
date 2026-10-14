# @roostorg/coop-pigeon

A [Coop](https://github.com/roostorg/coop) integration that scores content with
an organization's Pigeon policies. Lives in this repo next to the Pigeon
service so API and plugin stay in sync.

It adds one signal, **Pigeon policy score** (`PIGEON_POLICY_SCORE`). Its
subcategories are the policies your organization has in Pigeon. Each rule picks
a policy and sets its own threshold, so the same signal can drive a proactive
rule (Harassment ≥ 0.9 → action) and a routing rule (Harassment ≥ 0.5 → review
queue).

- Catalog: `GET /v1/policies` on catalog refresh.
- Scoring: `POST /v1/classify` with `{"model": "<policy id>", "input": {"text": "..."}}`.
  The score is `results[0].score`, from 0 to 1.
- Input: text (`STRING`) only. Pigeon's policy path does not accept images yet.

## Configuration

### Organization settings (Coop integration page)

| Field                | Required | Description                                                                                                                |
| -------------------- | -------- | -------------------------------------------------------------------------------------------------------------------------- |
| API key (`apiKey`)   | Yes      | Pigeon bearer token. It decides which Pigeon org's policies you see.                                                       |
| Base URL (`baseUrl`) | No       | Pigeon origin, e.g. `https://pigeon.example.com`. No path, query, or credentials. Leave blank to use the operator default. |

### Evaluation context (Coop-owned)

Coop shows an **Evaluation context** section on the Pigeon integration page
(from `manifest.contextOptions`). Orgs choose, per org:

| Context     | Default     | Notes                                                                   |
| ----------- | ----------- | ----------------------------------------------------------------------- |
| Parent item | **Include** | The item a reply answers (the item type's `parentId` role).             |
| Thread      | **Off**     | Earlier messages in the conversation; max **10** by default, up to 100. |

Those choices are **not** in `getCredential()`. Coop passes the loaded
context as `input.context` into `run()`, and the plugin flattens it into the
classify text (Pigeon has no separate context field):

```text
In reply to [<creator id>]: <parent text>

Earlier messages in this thread (oldest first):
[<creator id>]: <message text>
[<creator id>]: <message text>

Message to evaluate:
<item text>
```

Sections without context are left out. The item and its parent are not
repeated in the thread history. Coop doesn't trim context by size, so the
plugin enforces Pigeon's 100,000-character limit: the oldest thread messages
are dropped first, the parent and the item are kept, and if even those don't
fit, only the item's text is sent. Without context, only the item's text is
scored.

### Operator environment variables (Coop server process)

| Variable                          | Description                                                                                                                                                                                                      |
| --------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `PIGEON_ALLOWED_HOSTS`            | Required. Comma-separated hosts the plugin may call, e.g. `pigeon.example.com,*.pigeon.example.com`. An entry may include a port (`127.0.0.1:8900`). `*.example.com` matches subdomains only, not `example.com`. |
| `PIGEON_DEFAULT_BASE_URL`         | Base URL used when an org leaves the field blank. It must also pass the allowlist.                                                                                                                               |
| `PIGEON_ALLOW_INSECURE_LOCALHOST` | `true`, `1`, or `yes` allows `http:` for `localhost`, `127.0.0.1`, and `[::1]`. For local development only.                                                                                                      |

Every other base URL must use `https:`. Requests use `redirect: 'error'`, so a
redirect can't send the API key to a host outside the allowlist.

## How policies map to subcategories

| Coop subcategory | Pigeon policy                                               |
| ---------------- | ----------------------------------------------------------- |
| `id`             | `id` (also the classify `model`)                            |
| `label`          | `display`, capped at 200 characters                         |
| `description`    | `Pigeon policy <id> (base model <base>, version <version>)` |
| `childrenIds`    | Always `[]`. Pigeon policies are not nested.                |

- The first 1,000 policies are used (Coop's limit), sorted by label.
- The catalog `version` is `sha256:` of the sorted `id@version` pairs, since
  Pigeon has no etag. It changes when a policy is added, removed, or edited.
- Rules store the policy id. Editing a policy in Pigeon keeps its id; creating it
  under a new name is a different policy, and existing rules won't follow it.
- Scoring always uses the policy's latest version.

## Errors admins may see

Plugin errors have the form `Pigeon <CODE>: <message>`. They never include API
keys, classified content, or raw Pigeon responses.

| Code                | Meaning                                                                                                                 | What to do                                                                 |
| ------------------- | ----------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| `NOT_CONFIGURED`    | No API key or no base URL. The signal also shows as disabled: "Add your Pigeon API key on the Pigeon integration page." | Enter the key (and base URL if there's no operator default).               |
| `INVALID_CONFIG`    | Malformed key, bad base URL, host not in `PIGEON_ALLOWED_HOSTS`, or `http:` URL.                                        | Fix the field named in the message, or ask the operator to allow the host. |
| `AUTH_FAILED`       | Pigeon returned 401 or 403.                                                                                             | Check the API key.                                                         |
| `POLICY_REQUIRED`   | A rule condition has no policy selected. Pigeon has no overall score.                                                   | Pick a policy in the condition.                                            |
| `UNKNOWN_POLICY`    | Classify returned 404: the policy was deleted or renamed.                                                               | Refresh the catalog and update the affected rules.                         |
| `UNSUPPORTED_INPUT` | The rule sent a non-text value.                                                                                         | Use a text field.                                                          |
| `INVALID_REQUEST`   | Pigeon returned 422, or the text is over 100,000 characters.                                                            | Check the input.                                                           |
| `TIMEOUT`           | Pigeon didn't answer in time (Coop's 10 s refresh limit, or the plugin's 8 s scoring limit).                            | Check Pigeon's health.                                                     |
| `NETWORK_ERROR`     | Pigeon couldn't be reached.                                                                                             | Check the base URL and the network.                                        |
| `UPSTREAM_ERROR`    | Any other non-2xx response, e.g. 429 or 5xx.                                                                            | Check Pigeon's logs.                                                       |
| `INVALID_RESPONSE`  | The response was malformed or larger than 1 MB.                                                                         | Check the Pigeon version.                                                  |

When a refresh fails, Coop keeps the last good catalog and shows the error on the
integration page, alongside its own reason codes (`TIMEOUT`, `PLUGIN_ERROR`,
`INVALID_CATALOG`, `COLLISION`). When a policy disappears from a successful
refresh, Coop marks the rules that use it as affected and notifies admins.

## Mock Pigeon server

For trying the integration without a Pigeon deployment:

```bash
npm run mock-server          # http://127.0.0.1:8900
```

It mirrors Pigeon's `GET /health`, `GET /v1/policies`, `POST /v1/policies`, and
`POST /v1/classify`, using `mock-server/fixtures.json`:

- Token `test-api-key` → org with policies `harassment`, `toxicity`, `spam`.
- Token `other-org-key` → org with no policies.
- Scores: 0.95 if the text contains a policy keyword (e.g. "idiot" for
  harassment), 0.6 for a medium keyword ("shut up"), otherwise a small fixed value.

Routes under `/__mock/` exist only in the mock, because Pigeon has no delete endpoint:

```bash
T=test-api-key
curl -s localhost:8900/v1/policies -H "Authorization: Bearer $T"
curl -s localhost:8900/v1/classify -H "Authorization: Bearer $T" -H 'Content-Type: application/json' \
  -d '{"model":"harassment","input":{"text":"you idiot"}}'
curl -s -X DELETE localhost:8900/__mock/policies/harassment -H "Authorization: Bearer $T"
curl -s -X POST localhost:8900/__mock/reset
```

`PORT`, `HOST` (default `127.0.0.1`), and `PIGEON_MOCK_FIXTURES` override the defaults.

## Try it in local Coop

1. From this directory: `npm install && npm run build`.
2. Point Coop at this package in `server/integrations.local.json` (path relative
   to the config file), for example:

   ```json
   {
     "integrations": [
       {
         "package": "../../pigeon/integrations/coop-pigeon",
         "enabled": true
       }
     ]
   }
   ```

   Or after publish: `"package": "@roostorg/coop-pigeon"`.

3. Start the mock server (or a real Pigeon on port 8900), then start Coop from `server/`:

   ```bash
   PIGEON_ALLOWED_HOSTS=127.0.0.1:8900 PIGEON_ALLOW_INSECURE_LOCALHOST=true \
   PIGEON_DEFAULT_BASE_URL=http://127.0.0.1:8900 \
   INTEGRATIONS_CONFIG_PATH=integrations.local.json npm start
   ```

4. On the Pigeon integration page, enter API key `test-api-key` and save; the save triggers a catalog refresh.
5. Create a proactive rule, "Pigeon policy score / Harassment ≥ 0.9", and a
   routing rule, "Pigeon policy score / Harassment ≥ 0.5 → review queue". Submit
   "you idiot" (both rules match) and "please shut up" (routing only).
6. Run `curl -X DELETE localhost:8900/__mock/policies/harassment -H "Authorization: Bearer test-api-key"`,
   click **Refresh catalog**, and confirm the rules show as affected.

Coop stores the refreshed, data-only catalog per organization and integration
in Postgres. On evaluation, every API instance rebuilds the runnable signal
with `createCatalogSignal`; the provider is not called for each run.

## Development

```bash
npm test         # mocked fetch plus the local mock server; no real Pigeon calls
npm run build    # compiles src/ to dist/
```

Depends on `@roostorg/coop-types` `^3.0.0` (published on npm).

## Publishing

CI publishes to npm when `integrations/coop-pigeon/**` changes on
`main` or `prototype` (see `.github/workflows/publish-coop-integration.yaml`).
Bump `version` in `package.json` to release; if that version already exists on
npm, the workflow skips. npm must have OIDC trusted publishing configured for
`@roostorg/coop-pigeon` (same pattern as Coop's `@roostorg/coop-types`).

## Known Pigeon API gaps

- No catalog etag, so the version is hashed client-side.
- No overall score when no policy is selected.
- No thread or context field on classify; the plugin flattens Coop's
  parent and thread context into `input.text` when present.
- No image input on the policy path (422).
- No endpoint to delete or rename a policy (the mock adds a delete route).
- No documented production hostname, hence the operator allowlist.

## License

Apache-2.0
