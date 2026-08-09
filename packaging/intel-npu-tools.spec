# RPM package for Fedora, RHEL and openSUSE.
#
# Installs the same tree as the Debian and Arch packages by calling the shared
# staging script, so the three cannot drift apart.
#
# The models and the OpenVINO runtime are deliberately absent: they are large,
# they are redistributed under their own licences, and OpenVINO is not in the
# distribution archives. Each user runs intel-npu-tools-setup once, which is
# also why nothing here touches the network — a maintainer script must not.
#
# Build with:
#   rpmbuild -bb packaging/intel-npu-tools.spec \
#            --define "_sourcedir $PWD" --define "_projectdir $PWD"

%global project %{?_projectdir}%{!?_projectdir:%{_sourcedir}}
%global debug_package %{nil}

Name:           intel-npu-tools
Version:        0.3.0
Release:        1%{?dist}
Summary:        Local speech, OCR and semantic search on the Intel AI Boost NPU

License:        MIT
URL:            https://github.com/etreby/intel-arrow-lake-npu-tools
BuildArch:      noarch

Requires:       python3 >= 3.10
Requires:       ffmpeg-free
Requires:       tesseract
Requires:       tesseract-langpack-eng
Requires:       pciutils

Recommends:     tesseract-langpack-ara
Recommends:     wl-clipboard
Recommends:     pipewire-utils
Recommends:     librsvg2-tools

Suggests:       gnome-screenshot
Suggests:       grim

%description
Makes the integrated Intel AI Boost NPU in Arrow Lake processors useful on
Linux. Provides private semantic search, local Whisper transcription,
screenshot text extraction, a control panel, and an MCP server that AI agents
can call to keep bulk text out of their context window.

The models and the OpenVINO runtime are not included, because they are large
and are redistributed under their own licences. Run intel-npu-tools-setup once
as your own user to create the environment and download them.

%prep
# Nothing to unpack: the package is built from the working tree.

%build
# Nothing to compile.

%install
%{project}/scripts/stage-package.sh %{buildroot} %{_prefix}

%files
%license %{_prefix}/lib/intel-npu-tools/LICENSE
%doc %{_datadir}/doc/intel-npu-tools
%{_bindir}/intel-npu-info
%{_bindir}/intel-npu-mcp
%{_bindir}/intel-npu-ocr
%{_bindir}/intel-npu-panel
%{_bindir}/intel-npu-search
%{_bindir}/intel-npu-speech
%{_bindir}/intel-npu-tools-setup
%{_prefix}/lib/intel-npu-tools
%{_datadir}/applications/intel-npu-speech.desktop
%{_datadir}/applications/intel-npu-ocr.desktop
%{_datadir}/applications/intel-npu-panel.desktop
%{_datadir}/icons/hicolor/*/apps/intel-npu-tools.*

%post
/bin/touch --no-create %{_datadir}/icons/hicolor &>/dev/null || :
cat <<'MESSAGE'

Intel NPU Tools is installed. Each user runs this once to create their
environment and download the models:

    intel-npu-tools-setup

MESSAGE

%postun
if [ $1 -eq 0 ] ; then
    /usr/bin/gtk-update-icon-cache %{_datadir}/icons/hicolor &>/dev/null || :
    /usr/bin/update-desktop-database &>/dev/null || :
fi
# A user's environment and models live in their home directory and are left
# alone: removing a package must not delete a user's data.

%posttrans
/usr/bin/gtk-update-icon-cache %{_datadir}/icons/hicolor &>/dev/null || :
/usr/bin/update-desktop-database &>/dev/null || :

%changelog
* Sat Aug 09 2026 Mohamed El-Etreby <40498+etreby@users.noreply.github.com> - 0.3.0-1
- Control panel, persistent settings, and desktop support beyond KDE
- context_filter and screen_to_text for reducing AI agent token use
- Optional cross-encoder reranking and a selectable speech model
