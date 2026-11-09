#!/usr/bin/env bash
# Package the already assembled Electron/PyInstaller payload with Fedora's tools.
set -euo pipefail
project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"
source "$project_root/scripts/toolchain.sh"
if ! command -v rpmbuild >/dev/null 2>&1; then
  echo "RPM packaging requires rpm-build (rpmbuild)." >&2
  exit 1
fi
payload="$project_root/dist/desktop/linux-unpacked"
if [[ ! -x "$payload/anki-generator" || ! -x "$payload/resources/backend/anki-generator-backend" ]]; then
  echo "Build the Electron directory payload before packaging the RPM." >&2
  exit 1
fi
version="$("${NODE:-node}" -p 'require("./desktop/package.json").version')"
architecture="$(rpm --eval '%{_arch}')"
glibc_version="$(getconf GNU_LIBC_VERSION)"
glibc_version="${glibc_version#glibc }"
rpm_root="$project_root/build/desktop/rpm"
mkdir -p "$rpm_root"/{BUILD,BUILDROOT,RPMS,SOURCES,SPECS,SRPMS}
rpmbuild --quiet -bb "$project_root/desktop/build/anki-generator.spec" \
  --define "_topdir $rpm_root" \
  --define "app_version $version" \
  --define "glibc_version $glibc_version" \
  --define "desktop_payload $payload" \
  --define "desktop_metadata $project_root/desktop/build"
artifact="$project_root/dist/desktop/Anki-Generator-$version-$architecture.rpm"
cp "$rpm_root/RPMS/$architecture/anki-generator-desktop-$version-1.$architecture.rpm" "$artifact"
echo "Fedora RPM: $artifact"
