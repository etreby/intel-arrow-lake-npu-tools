# Security policy

Please report security issues privately through GitHub's security advisory feature instead of a public issue.

The installer uses `sudo` only for distribution packages, Intel's signed NPU packages, and group membership. Review scripts before running them. Models are downloaded from OpenVINO/Hugging Face upstream locations. MCP is local stdio and does not listen on a network port.
