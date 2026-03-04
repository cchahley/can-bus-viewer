# Company-Safe Dependency and License Signoff Checklist

Use this checklist before each release of CAN Bus Viewer.

## 1. Lock the shipped dependency set

- Record exact versions that will ship (`requirements.txt`, lock file, or `pip freeze` output).
- Save the dependency snapshot with the release artifacts.

## 2. Verify runtime dependency licenses

- `python-can`: LGPL-3.0-only
- `cantools`: MIT
- `matplotlib`: Matplotlib/PSF-style permissive license, with bundled third-party components under additional permissive terms (for example MIT/BSD/OFL)
- `pyserial` (if included): BSD

## 3. Validate LGPL compliance obligations (`python-can`)

- Confirm distribution model (internal installer, external installer, portable bundle, etc.).
- Confirm required notices and source/license availability steps per company legal guidance.
- Confirm process for replacing/relinking LGPL-covered components where required by policy.

## 4. Include notices in distributed artifacts

- Add project `LICENSE` file.
- Add `THIRD_PARTY_NOTICES.md` with package names, versions, and licenses.
- Ensure installer/package includes both files.

## 5. Guard against disallowed licenses

- Re-scan dependencies for any GPL-only (or otherwise policy-blocked) runtime packages.
- Confirm newly added transitive dependencies are reviewed.

## 6. Separate runtime vs dev/build tooling

- Runtime dependencies are only those required to run the application.
- Dev/build tools remain non-runtime (`pytest`, `ruff`, `mypy`, `pyinstaller`).

## 7. Run security and license scanning

- Run SCA/license scan in CI (or approved internal tool).
- Resolve policy blockers before release.
- Record scan date and tool/report ID.

## 8. Generate and archive SBOM/reporting

- Produce SBOM (or equivalent dependency report) for the exact shipped build.
- Archive report with release artifacts.

## 9. Signoff and audit trail

- Engineering owner approval recorded.
- Legal/compliance approval recorded.
- Final release ticket references checklist completion.

## Release Record (fill per release)

- Release version:
- Release date:
- Dependency snapshot file:
- License scan report:
- SBOM/report artifact:
- Engineering approver:
- Legal/compliance approver:
- Notes/exceptions:

Current planned release version: `0.1.0`
