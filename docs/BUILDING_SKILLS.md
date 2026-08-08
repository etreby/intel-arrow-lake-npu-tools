# Building agent skills with the NPU tools

An agent skill supplies a repeatable workflow around the MCP tools. It does not duplicate the embedding implementation.

## Included example

The repository includes `examples/skills/intel-npu-local-knowledge/`, containing a concise `SKILL.md` and Codex UI metadata. Copy it into the skill directory used by your agent, then restart the agent.

```bash
cp -a examples/skills/intel-npu-local-knowledge ~/.codex/skills/
```

The skill assumes the MCP server exposes the three semantic tools.

## Design your own skill

Use a lowercase hyphenated folder name and include a `SKILL.md` with only `name` and `description` in its YAML frontmatter. Put triggering conditions in the description and keep the body focused on the procedure.

A useful retrieval workflow should:

1. Inspect `semantic_index_status` before indexing.
2. Index only an explicitly scoped path.
3. Search with a focused question and an appropriate root filter.
4. Cite returned paths and line numbers.
5. Treat similarity as ranking rather than factual confidence.
6. Verify critical claims against source files when possible.

Do not instruct an agent to index an entire home directory, credential stores, browser profiles, or secret directories. Skills should preserve the local-only privacy boundary of the MCP server.

Validate Codex-compatible skills with the `quick_validate.py` utility from Codex's skill-creator package when available.
