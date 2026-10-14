# Integrations

Packages that connect Pigeon to consumer tools.

| Package | npm | Description |
| --- | --- | --- |
| [`coop-pigeon`](./coop-pigeon) | `@roostorg/coop-pigeon` | Coop plugin: one signal, org policies as subcategories |

Publishing for the Coop package is handled by
[`.github/workflows/publish-coop-integration.yaml`](../.github/workflows/publish-coop-integration.yaml)
when files under `integrations/coop-pigeon/` change on `main` or
`prototype`. Bump `package.json` `version` (and `PACKAGE_VERSION` in
`src/constants.ts`) to cut a release.
