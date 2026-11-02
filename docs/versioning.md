# Versioning

This project follows **SemVer 2.0.0**: `MAJOR.MINOR.PATCH`, tagged `vX.Y.Z`.

- **MAJOR** — incompatible public API or behaviour (Python API, Java core,
  protocol semantics).
- **MINOR** — compatible features, new platform, new status field.
- **PATCH** — fixes and docs, no API change.
- While `0.x`, MINOR may still carry breaking changes; call them out in the
  changelog.
- `1.0.0` when the API is stable and the platform matrix is honest.

Keep these in sync for every release:

```text
pyproject.toml        version
it9308/__init__.py    __version__
git tag               vX.Y.Z
CHANGELOG.md          section for X.Y.Z
release.ps1 -Version  X.Y.Z
```

The vendor firmware version (`1.10.0.0`) is separate and must not be used as
the driver version.

Artifacts, if any are published, are named `it9308-<version>-<YYMMDD>.zip`;
source releases stay binary-free.
