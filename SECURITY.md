# Security policy

Please report security issues privately through GitHub's security advisory feature instead of a public issue.

The installer uses `sudo` only for distribution packages, Intel's NPU packages, and group membership. Review scripts before running them. Models are downloaded from OpenVINO/Hugging Face upstream locations. MCP is local stdio and does not listen on a network port.

Driver downloads are verified before installation:

- Every Intel NPU `.deb` the installer passes to `apt-get` is GPG-verified against the pinned key fingerprint in `scripts/install-intel-npu-driver-ubuntu.sh`. A package without a valid detached signature, or an expected package missing from the archive, aborts the install.
- The Level Zero loader `.deb` is not signed on its PPA snapshot path, so it is pinned by SHA-256 and the installer aborts on a digest mismatch.

`uninstall.sh` canonicalizes `INTEL_NPU_TOOLS_HOME` before deleting it and refuses any value that does not resolve to a subdirectory of your home directory.
