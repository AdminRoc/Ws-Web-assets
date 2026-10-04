# EELog Runtime Release

This release family contains only public runtime assets consumed by the EELog analyzer:

```text
js/wf-translations.js
data/i18n/wf-i18n.json
```

The descriptor at `data/eelog-runtime-release.json` records one immutable assets revision and the SHA-256 of every member. It does not replace or delete:

- EELog local `data/arb-node-baseline.js` worker seed;
- EELog local fixed arbitration baseline JSON and its lookup logic;
- EELog local i18n/category fallback data;
- `log/js/solNodes.js`;
- any EELog parser logic.

The `publish-runtime-data.yml` workflow updates this descriptor only after the selected translation dependencies pass public CDN byte-for-byte readback. It uses the latest commit touching the two runtime artifacts, so unrelated public asset commits do not change the release family. The older standalone hourly descriptor writer has been retired because it could publish readiness metadata without first verifying those dependencies. The arbitration baseline is no longer part of this release: EELog scores with its fixed local standard, and the current Assets baseline files are retained as inactive snapshots. The helper can still be run manually for local inspection after both public translation artifacts are present in one Assets checkout:

```powershell
python tools/build_eelog_runtime_release.py --assets-revision <assets-commit-sha>
```

Consumers must load both remote translation members from `Ws-Web-assets@<assetsRevision>`, never independently from mutable `@main` paths.
