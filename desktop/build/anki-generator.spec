# Fedora package for electron-builder's Linux directory payload.
# Native rpmbuild avoids FPM's legacy Ruby/libcrypt build dependency.
%global debug_package %{nil}
%global _build_id_links none
%global source_date_epoch_from_changelog 0
%global _binary_payload w7T2.zstdio

Name: anki-generator-desktop
Version: %{app_version}
Release: 1
Summary: Generate evidence-backed university flashcards
License: LicenseRef-Proprietary
URL: https://github.com/davidsnik/Anki-Generator
AutoReqProv: no
Requires: glibc%{?_isa} >= %{glibc_version}
Requires: glib2%{?_isa}, gtk3%{?_isa}, nss%{?_isa}, nspr%{?_isa}
Requires: alsa-lib%{?_isa}, cups-libs%{?_isa}, at-spi2-core%{?_isa}
Requires: libX11%{?_isa}, libXcomposite%{?_isa}, libXdamage%{?_isa}
Requires: libXext%{?_isa}, libXfixes%{?_isa}, libXrandr%{?_isa}
Requires: libxcb%{?_isa}, libxkbcommon%{?_isa}, mesa-libgbm%{?_isa}
Requires: libdrm%{?_isa}, libgcc%{?_isa}, libstdc++%{?_isa}, libsecret%{?_isa}
Requires: xdg-utils

%description
A local desktop application for turning university source material into
evidence-backed Anki flashcards, with human review and stable deck identities.
The application includes Electron, its Python backend and frontend resources.
OpenAI processing requires explicit consent, network access and an API key.

%prep

%build

%install
mkdir -p "%{buildroot}/opt/anki-generator"
cp -a "%{desktop_payload}/." "%{buildroot}/opt/anki-generator/"
install -Dm644 "%{desktop_metadata}/anki-generator.desktop" \
  "%{buildroot}/usr/share/applications/org.anki_generator.AnkiGenerator.desktop"
for size in 16 24 32 48 64 128 256 512; do
  install -Dm644 "%{desktop_metadata}/icons/${size}x${size}.png" \
    "%{buildroot}/usr/share/icons/hicolor/${size}x${size}/apps/anki-generator.png"
done
for item in "%{buildroot}"/opt/anki-generator/*; do
  filename="${item##*/}"
  if [ "$filename" != chrome-sandbox ]; then
    printf '"/opt/anki-generator/%s"\n' "$filename"
  fi
done > "%{_builddir}/desktop-payload-files.txt"

%post
if [ -x /usr/bin/update-desktop-database ]; then
  /usr/bin/update-desktop-database -q /usr/share/applications || :
fi
if [ -x /usr/bin/gtk-update-icon-cache ]; then
  /usr/bin/gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || :
fi

%postun
if [ -x /usr/bin/update-desktop-database ]; then
  /usr/bin/update-desktop-database -q /usr/share/applications || :
fi
if [ -x /usr/bin/gtk-update-icon-cache ]; then
  /usr/bin/gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || :
fi

%files -f %{_builddir}/desktop-payload-files.txt
%defattr(-,root,root,-)
%dir /opt/anki-generator
# Standard Chromium setuid helper; renderer sandboxing remains enabled.
%attr(4755,root,root) /opt/anki-generator/chrome-sandbox
/usr/share/applications/org.anki_generator.AnkiGenerator.desktop
/usr/share/icons/hicolor/*/apps/anki-generator.png
