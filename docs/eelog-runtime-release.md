# EELog Runtime Release

This release family contains only public runtime assets consumed by the EELog analyzer:

```text
js/wf-translations.js
data/i18n/wf-i18n.json
data/arbitration-metrics/arb-node-baseline.js
data/arbitration-metrics/arb-node-baseline.json
```

The descriptor at `data/eelog-runtime-release.json` records one immutable assets revision and the SHA-256 of every member. It does not replace or delete:

- EELog local `data/arb-node-baseline.js` worker seed;
- EELog local i18n/category fallback data;
- `log/js/solNodes.js`;
- any EELog parser logic.

The hourly descriptor workflow uses the latest commit touching the four runtime artifacts, so it remains unchanged when unrelated public assets update. Generate manually after the four public artifacts are present in one assets checkout:

```powershell
python tools/build_eelog_runtime_release.py --assets-revision <assets-commit-sha>
```

Consumers must load all remote members from `Ws-Web-assets@<assetsRevision>`, never independently from mutable `@main` paths.
