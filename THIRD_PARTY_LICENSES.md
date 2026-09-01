# Third-party software

NemoFold uses `pypdf` (BSD-3-Clause) for local PDF text extraction and the official
Model Context Protocol Python SDK `mcp` (MIT) for its stdio MCP server. DOCX and ODT
text extraction use Python's standard ZIP/XML libraries. Test tooling is declared as
an optional development dependency.

`report-forge` (MIT, github.com/ellmos-ai/report-forge) is an optional dependency
behind the `templates` extra. It fills .docx templates, which is a separate job with
its own accumulated knowledge; none of its code is vendored here, and only its finish
stage is called. Without the extra, template workflows end blocked with the install
command rather than failing on an import. It is pinned to a commit rather than a
release tag because the repository publishes no tags, and a pin to a tag that does not
exist would break every install.

NemoClaw, OpenShell, OpenClaw, Nemotron, and Nebius are external runtimes or services;
their source code is not vendored into this repository. Their names identify integration
targets and do not imply ownership or endorsement.
