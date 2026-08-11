# Docker, Flatpak, Snap and AppImage

A feasibility assessment, not a plan. Nothing here has been built or tested;
where a verdict depends on something that would have to be tried, it says so.

The five native packages this project already ships — `.deb`, RPM for Fedora,
openSUSE and Enterprise Linux, and Arch — are all *thin*. They install code and
wrappers, and each user then runs `intel-npu-tools-setup`, which builds a
virtual environment and downloads about 800 MB of models into their home
directory. Nothing is bundled, and every one of the formats below is really a
question about bundling.

## What any format has to provide

Five requirements, all of them read out of this repository rather than
assumed.

**1. The NPU itself.** `/dev/accel/accel0` must be readable and writable, which
means the process needs the `render` group — `install-intel-npu-driver-ubuntu.sh`
runs `usermod -aG render`, and `TROUBLESHOOTING.md` opens by checking exactly
that. The device node is not sufficient on its own: OpenVINO's NPU plugin talks
to it through Intel's userspace, `intel-driver-compiler-npu`, `intel-fw-npu`,
`intel-level-zero-npu` and the Level Zero loader `libze1`. Those are versioned
against the kernel's `intel_vpu` driver, and the installer pins a *dated PPA
snapshot* rather than tracking latest, which tells you how tight the coupling
is. Any bundle carries a copy of that userspace and has to stay compatible with
whatever kernel the host is running.

**2. Desktop tools that live on the host.** `desktop.py` picks a screenshot
command from `spectacle`, `cosmic-screenshot`, `gnome-screenshot`, `grim`,
`maim`, `scrot` and ImageMagick, and a clipboard command from `wl-copy`,
`xclip` and `xsel`. Audio capture shells out to PipeWire's tools or `ffmpeg`.
Every one of these is a host binary invoked as a subprocess. A sandbox that
cannot see the host's `PATH` cannot use any of them, and this is the single
biggest obstacle for the two sandboxed formats.

**3. Roughly 800 MB of models**, downloaded after installation, owned by the
user, and deliberately not in any package — they are large and separately
licensed. Whatever the format, this stays a post-install step, and the format
has to leave the user a writable directory that survives updates.

**4. An MCP server the host's agent can launch.** Registration points an agent
CLI at `/usr/bin/intel-npu-mcp` and talks stdio. Whatever replaces that path
must be launchable by a process outside the bundle.

**5. Global shortcuts.** `install.sh` writes into KDE's `kglobalshortcutsrc`,
because that is the only file KDE reads. A sandboxed application cannot write
to it.

## Summary

| | Docker | Flatpak | Snap | AppImage |
|---|---|---|---|---|
| `/dev/accel` | `--device` + `--group-add render` | only via `--device=all` | `accel` interface not usable yet | host device, no mediation |
| Host capture/clipboard | no | portals, after a rewrite | portals, after a rewrite | yes |
| MCP server | good fit | workable | workable | yes |
| Global shortcuts | no | portal, KDE yes / GNOME no | same | yes |
| Bundles Intel userspace | yes, pinned | yes | Canonical ships one | fragile |
| Verdict | **worth doing, headless only** | **possible, expensive** | **blocked today** | **little gained** |

## Docker — worth doing, for the headless half

The half of this project that needs no desktop is substantial: the MCP server,
`semantic_search`, `context_filter`, `transcribe_audio` and `ocr_image` all run
without a screen. For that half a container is a good fit and the device story
is the simple one — pass `--device /dev/accel/accel0` and `--group-add render`,
with no sandbox to negotiate with.

The version coupling in requirement 1 is the real work, and this repository
already contains the recipe: `install-intel-npu-driver-ubuntu.sh` pins exact
`.deb` URLs from a dated PPA snapshot. An image pinning those same versions is
reproducible, and the only compatibility question left is between that pinned
userspace and the host's kernel driver, which is a question that has to be
answered by testing on a real host rather than reasoned about.

`docker run -i` as the MCP command is a natural fit: the server is long-lived
stdio, so image startup is paid once per agent session rather than per call.
Bind-mount the model directory so the download is not repeated per container.

What it cannot do is the desktop half — screenshots, clipboard, the control
panel, global shortcuts. That is not a limitation to work around; it is the
correct division.

## Flatpak — possible, but it is a rewrite

Two problems, one soluble and one a real cost.

**The device.** Flatpak's `--device=` takes `dri`, `kvm`, `shm`, `input`, `usb`
and `all`, and the documentation describes `dri` as the Direct Rendering
Interface, necessary for GL. `/dev/accel` is not `/dev/dri`, and no value other
than `all` covers it. So an NPU application needs `--device=all`, which grants
every device on the machine. That is a legitimate manifest, but it means the
sandbox argument for Flatpak is much weaker here than for an ordinary app, and
reviewers on Flathub will ask about it.

**The host tools.** This is the expensive part. `desktop.py`'s design — probe
for seven screenshot binaries, pick one that matches the running desktop —
cannot work inside a sandbox at all. The replacement is
`org.freedesktop.portal.Screenshot`, and the good news is better than expected:
the portal supports non-interactive capture, KDE skips the dialog for
non-interactive requests, and GNOME grants a permission once after which the
app can capture with `interactive` set to false and no visible window. So
instant capture on a keyboard shortcut *is* achievable, which was the thing
most likely to have killed this outright.

Global shortcuts have a portal too, `org.freedesktop.portal.GlobalShortcuts`,
implemented by KDE — using KGlobalAccel underneath, the same mechanism
`install.sh` writes to today — and by Hyprland. GNOME's support is still an
open request, so on GNOME a Flatpak build would have no global shortcuts at
all.

Worth being fair about the upside: a portal rewrite of `desktop.py` would
replace seven binary probes with one interface that works on every desktop
implementing portals, including ones nobody has tested. That is architecturally
better than what exists now, sandbox or no sandbox. The cost is that it is a
rewrite of the desktop integration layer, plus bundling OpenVINO and Intel's
NPU userspace into the runtime, plus `--device=all`.

## Snap — blocked today, for a specific reason

Snap has an `accel` interface, intended for exactly this: access to device
nodes in `/dev/accel` managed by the Linux compute accelerator subsystem. Its
own documentation describes it as under development and not currently
available for general use. Until that changes, a strictly confined snap cannot
reach the NPU, and the only route is classic confinement — which switches off
the confinement that is the reason to choose Snap.

Canonical does publish an Intel NPU driver snap providing the userspace
components, so the bundling problem is further along here than anywhere else,
and the same non-root requirements apply: the user in the `render` group and
the device node group-writable.

The desktop-tool problem is identical to Flatpak's and has the same portal
answer. The sensible reading is that Snap is Flatpak's work plus a blocker
nobody here controls, so if only one sandboxed format is ever done, it should
be Flatpak.

## AppImage — least gained

An AppImage would work, in the sense that nothing structurally prevents it: no
sandbox, so host screenshot and clipboard tools are reachable and global
shortcuts can be written normally.

The problem is that it buys almost nothing. AppImage's selling point is a
single portable file with no installation, and this project's payload is a
per-user virtual environment plus 800 MB of downloaded models — neither of
which an AppImage removes. It would have to bundle OpenVINO, which is large,
and Intel's NPU userspace, which links against host libraries and is the part
of the stack least tolerant of being carried around. Meanwhile the five native
packages already install cleanly on every distribution they target and are
verified doing so on every push.

The one real gap AppImage could fill is a distribution with no package here at
all — Gentoo, NixOS, Void. That is a thinner reason than it first appears,
since users of those distributions generally prefer a native definition, and
`stage-package.sh` already makes writing one cheap.

## If any of this gets built

Test on real hardware, not in CI. GitHub's runners have no NPU, so every job in
`validate.yml` verifies packaging and never touches the device. A container or
bundle can be *built* in CI and proved to contain what it should, in exactly
the way the native packages are, but whether its pinned Intel userspace talks
to a given host kernel driver can only be answered on a machine with the
hardware.

Sources for the claims about other projects' tooling:

- [Flatpak sandbox permissions](https://docs.flatpak.org/en/latest/sandbox-permissions.html) — the `--device=` values
- [Snap `accel` interface](https://snapcraft.io/docs/reference/interfaces/accel-interface/) — under development, not generally available
- [Intel NPU driver snap](https://github.com/canonical/intel-npu-driver-snap) — Canonical's userspace packaging
- [`org.freedesktop.portal.GlobalShortcuts`](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.GlobalShortcuts.html)
- [Screenshot portal permission](https://github.com/flatpak/xdg-desktop-portal/pull/851) — non-interactive capture after a one-time grant
