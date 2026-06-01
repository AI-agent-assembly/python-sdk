> **Pre-release dry-run.** Third pre-release in the v0.0.1 series.
> Continues exercising the cross-repo release CD pipeline while
> verifying the 3 release-infra fixes that landed since v0.0.1-alpha.2.

### 🔒 Release-infra fixes verified by this tag

* **AAASM-2188 (PR agent-assembly#832)** — Docker matrix parallel cargo
  cache race condition: `failed to unpack base64ct-1.8.3: File exists
  (os error 17)`. Fixed by per-Dockerfile cache `id` + `sharing=locked`
  in all 6 language Dockerfiles.
* **AAASM-2189 (PR python-sdk#68)** — `Release Python SDK` maturin
  wheel builds: missing `protoc` in manylinux container. Fixed by
  downloading official protoc 32.1 binary in `before-script-linux`
  (CentOS 7's yum-packaged protoc 2.5.0 doesn't support proto3 syntax).
  Hardened with SHA256 verification + `--retry` for supply-chain
  + network resilience.
* **AAASM-2190 (PR node-sdk#59)** — `release.yml` `pnpm publish`
  E402 Payment Required for scoped package `@agent-assembly/sdk`.
  Fixed by adding `--access public` (matching the sibling
  release-node.yml's existing pattern).

### Install

```bash
pip install --pre agent-assembly==0.0.1a3
```

### Refs

* Bump: `AAASM-2313`
* Verify: `AAASM-2316`
* Sibling tags: `agent-assembly v0.0.1-alpha.3`, `node-sdk v0.0.1-alpha.3`, `go-sdk v0.0.1-alpha.3`
