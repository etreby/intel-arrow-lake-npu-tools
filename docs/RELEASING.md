# Releasing

Pushing a `v*` tag builds the wheel, the source distribution and the `.deb`,
attaches all three to a GitHub release, and republishes the signed apt
repository to GitHub Pages. Everything else here is the setup that has to
happen once.

## Cutting a release

```bash
# The workflow refuses a tag that disagrees with pyproject.toml, so change the
# version first and let the tag follow it.
git tag -a v0.3.0 -m "Intel NPU Tools 0.3.0"
git push origin v0.3.0
```

The release notes come from the top section of `CHANGELOG.md`, so write that
before tagging rather than editing the release afterwards.

## One-time setup: the apt signing key

A repository apt will accept has to be signed. Modern apt refuses an unsigned
repository outright rather than warning about it, so this is not optional, and
the key has to be one you hold: it is the only thing standing between your
users and someone else's packages.

**Generate a signing key.** Use a key dedicated to this, not your personal
one — it lives in a CI secret, and a key with one job can be revoked without
touching anything else.

```bash
gpg --quick-generate-key "Intel NPU Tools <you@example.com>" default sign never
gpg --list-secret-keys --keyid-format=long        # note the key id
```

**Add it to the repository as a secret.** The workflow imports it for the
length of one job and never writes it anywhere.

```bash
gpg --armor --export-secret-keys <KEY_ID> | gh secret set APT_GPG_PRIVATE_KEY
```

**If the key has a passphrase, `APT_GPG_PASSPHRASE` is not optional.** Signing
runs unattended, so a protected key with no passphrase available fails with:

```
gpg: Sorry, we are in batchmode - can't get input
```

That message is the whole diagnosis: the key imported fine and gpg is asking
for something nothing can answer. Add it, or export a key with no passphrase
for continuous integration and keep the protected one offline.

```bash
gh secret set APT_GPG_PASSPHRASE    # prompts; nothing is echoed or stored locally
```

**Enable GitHub Pages** for the repository, with "GitHub Actions" as the
source. Settings → Pages → Build and deployment → Source.

Until `APT_GPG_PRIVATE_KEY` exists the apt job skips itself and says so. The
release still happens; only the repository is not published. That is
deliberate — a release that half-fails because a secret is missing is worse
than one that tells you which secret to add.

**Back the key up somewhere offline.** Losing it means every existing user has
to remove the old keyring and add a new one by hand, because apt will reject a
repository signed by a key it does not know.

## What users then run

```bash
curl -fsSL https://etreby.github.io/intel-arrow-lake-npu-tools/apt/intel-npu-tools-archive-keyring.gpg \
  | sudo tee /etc/apt/keyrings/intel-npu-tools.gpg > /dev/null

echo "deb [signed-by=/etc/apt/keyrings/intel-npu-tools.gpg] https://etreby.github.io/intel-arrow-lake-npu-tools/apt ./" \
  | sudo tee /etc/apt/sources.list.d/intel-npu-tools.list

sudo apt update && sudo apt install intel-npu-tools
intel-npu-tools-setup
```

## Building any of it by hand

```bash
python -m build                                   # wheel and sdist
./scripts/build-deb.sh dist                       # .deb
./scripts/build-apt-repo.sh public/apt dist/*.deb # signed repository
```

`build-apt-repo.sh` signs with the only secret key in your keyring unless
`APT_GPG_KEY_ID` names one, and refuses to run if there is no key at all
rather than producing a repository nobody can install from.

## What is not automated

The Arch and RPM packages are built by hand. Neither `makepkg` nor `rpmbuild`
runs on the Ubuntu image the workflow uses, and cross-building them there would
produce packages nobody had tested on the distribution they target.

```bash
cd packaging && makepkg -si
rpmbuild -bb packaging/intel-npu-tools.spec --define "_projectdir $PWD"
```
