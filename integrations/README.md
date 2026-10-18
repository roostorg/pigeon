# Integrations

Packages that connect Pigeon to consumer tools.

| Package | npm | Description |
| --- | --- | --- |
| [`pigeon-coop`](./pigeon-coop) | `@roostorg/pigeon-coop` | Coop plugin: one signal, org policies as subcategories |

Publishing for the Coop package is handled by
[`.github/workflows/publish-coop-integration.yaml`](../.github/workflows/publish-coop-integration.yaml)
when files under `integrations/pigeon-coop/` change on `main` or
`prototype`. Bump `package.json` `version` (and `PACKAGE_VERSION` in
`src/constants.ts`) to cut a release.
