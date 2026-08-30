# Third-party software

NemoFold uses `pypdf` (BSD-3-Clause) for local PDF text extraction. DOCX and ODT text
extraction use Python's standard ZIP/XML libraries. Test tooling is declared as an
optional development dependency.

NemoClaw, OpenShell, OpenClaw, Nemotron, and Nebius are external runtimes or services;
their source code is not vendored into this repository. Their names identify integration
targets and do not imply ownership or endorsement.
