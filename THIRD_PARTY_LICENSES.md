# Third-Party Licenses & Dependency Inventory

> **Project:** `ellmos-ai/NemoFold`<br>
> **Version:** `0.2.0`<br>
> **Audited:** 2026-09-18<br>
> **Repository License:** [MIT License](LICENSE)<br>
> **Architecture & Privacy:** 100% Local-First, Zero-Egress by default, Unprivileged User-Mode (`RunAsInvoker`)

---

## 1. Executive Summary & Compliance Assurance

NemoFold is a private, evidence-first document agent engineered with reversible actions, persistent local memory, exact citations, and bounded external reasoning.

The core runtime strictly enforces a **Zero-Copyleft Guarantee**:
- All direct and indirect runtime dependencies are distributed under strictly **permissive open-source licenses** (MIT, BSD-3-Clause, PSFL-2.0).
- There are **zero AGPL, GPL, or copyleft dependencies** in the core runtime or packaging harness.
- User files, extracted text, persistent SQLite indices, and generated reports remain 100% owned by the user.
- The software runs entirely in unprivileged user space (`RunAsInvoker`) without requiring root, administrator rights, or background daemon installation.

### Governance & Runtime Invariants Matrix

NemoFold complies with ten canonical governance and runtime invariants:

| Invariant ID | Name | Architectural Guarantee | Compliance Status |
|:---:|:---|:---|:---:|
| **INV-LOCAL-01** | 100% Local-First & Zero-Egress | Original documents, absolute paths, FTS index, policies, and ledger remain strictly local on host; zero automatic telemetry. | :white_check_mark: Verified |
| **INV-EVID-02** | Byte-Exact Evidence Citation | Claims accepted only when verbatim quotes match source text byte-for-byte; line and page locators preserved. | :white_check_mark: Verified |
| **INV-ACTION-03** | Reversible Actions & Journaled Undo | File mutations require pre-flight dry-run, atomic commit, and provide full reversible undo and resume via run journal. | :white_check_mark: Verified |
| **INV-GATE-04** | Multi-Tier Explicit Approval Gates | File actions, external model transfers, cloud spend ceilings, and network exposure require explicit operator flags. | :white_check_mark: Verified |
| **INV-ISOL-05** | Path-Free Sanitized Packaging | Outbound packages strip host paths, secrets, symlinks, and unapproved files; preflight validates package before network transit. | :white_check_mark: Verified |
| **INV-PROV-06** | Provider-Neutral Loopback Surface | Pluggable local and remote backends; unauthenticated interfaces and Captain's Desk restricted strictly to loopback (127.0.0.1). | :white_check_mark: Verified |
| **INV-POLICY-07** | Composable Primitives & Voyages | 4 shared primitives compose 34 document workflows; reusable voyage drafts adapt without model fine-tuning. | :white_check_mark: Verified |
| **INV-RUNAS-08** | Unprivileged User-Mode (`RunAsInvoker`) | Operates entirely under standard user privileges (`RunAsInvoker`); zero system daemon or administrative elevation required. | :white_check_mark: Verified |
| **INV-DET-09** | Deterministic Artifacts & Ledgers | Deterministic SVG figures, structured reports, and cryptographic SHA-256 run ledgers guarantee reproducible audit trails. | :white_check_mark: Verified |
| **INV-SLA-10** | 48h Security & Triage SLA | Security vulnerability disclosures acknowledged within 48h; triage and remediation assessment completed within 5 business days. | :white_check_mark: Verified |

---

## 2. Runtime Dependency Inventory

| Package | Version Range | SPDX License | Purpose / Functional Scope | Upstream Origin |
|:---|:---|:---|:---|:---|
| **mcp** | `>=1.27, <2` | `MIT` | Official Model Context Protocol SDK for stdio MCP server (`nemofold-mcp`) | [modelcontextprotocol/python-sdk](https://github.com/modelcontextprotocol/python-sdk) |
| **pypdf** | `>=6, <7` | `BSD-3-Clause` | Local offline PDF text and layout extraction | [py-pdf/pypdf](https://github.com/py-pdf/pypdf) |
| **Python Standard Library** | `>=3.11` | `PSFL-2.0` | ZIP/XML extraction (`zipfile`, `xml.etree`), SQLite FTS5 store (`sqlite3`), HTTP server (`http.server`), JSON schemas (`json`, `re`, `hashlib`, `pathlib`) | [python/cpython](https://github.com/python/cpython) |

---

## 3. Optional Extras & Composed Dependencies

| Package | Extra Target | SPDX License | Purpose / Functional Scope | Upstream Origin |
|:---|:---|:---|:---|:---|
| **report-forge** | `templates` | `MIT` | Filling .docx document templates; called strictly at finish stage. Pinned commit reference. | [ellmos-ai/report-forge](https://github.com/ellmos-ai/report-forge) |

*Notice:* Without the `templates` extra, template-filling workflows end blocked with the exact install command rather than failing on an import error.

---

## 4. Development, Quality Assurance & Build Tooling

| Package | Version Range | SPDX License | Purpose / Functional Scope | Upstream Origin |
|:---|:---|:---|:---|:---|
| **pytest** | `>=8.0` | `MIT` | Automated test runner and contract verification suite | [pytest-dev/pytest](https://github.com/pytest-dev/pytest) |
| **ruff** | `>=0.6` | `MIT` / `Apache-2.0` | Fast AST code linter and formatting enforcement | [astral-sh/ruff](https://github.com/astral-sh/ruff) |
| **mypy** | `>=1.11` | `MIT` | Static type checking and contract boundary verification | [python/mypy](https://github.com/python/mypy) |
| **hatchling** | `>=1.26` | `MIT` | PEP 517 / PEP 621 compliant build backend | [pypa/hatch](https://github.com/pypa/hatch) |
| **openpyxl** | `>=3.1.0` | `MIT` | Offline XLSX workbook export verification in test suite | [openpyxl/openpyxl](https://foss.heptapod.net/openpyxl/openpyxl) |
| **build** | `>=1.2` | `PyPA / MIT` | PEP 517 distribution package builder | [pypa/build](https://github.com/pypa/build) |

---

## 5. External Integration Targets & Trademarks

NemoClaw, OpenShell, OpenClaw, Nemotron, NVIDIA, and Nebius are external runtimes, models, or cloud platforms; their source code is not vendored into this repository. Their names identify integration targets, compatibility interfaces, or benchmark baselines, and do not imply ownership or endorsement.

---

## 6. License Texts (Excerpts & Notices)

### MIT License (MIT)
*Applies to `mcp`, `report-forge`, `pytest`, `hatchling`, `openpyxl`, `build`, and `NemoFold`.*

```text
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

### BSD 3-Clause License
*Applies to `pypdf`.*

```text
Copyright (c) 2006-2008, Mathieu Fenniak
Copyright (c) 2007, Ashish Kulkarni <kulkarni.ashish@gmail.com>
Copyright (c) 2014, Steve Witham <switham@tiac.net>
Copyright (c) 2022-2026, Martin Thoma

All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

* Redistributions of source code must retain the above copyright notice, this
  list of conditions and the following disclaimer.
* Redistributions in binary form must reproduce the above copyright notice,
  this list of conditions and the following disclaimer in the documentation
  and/or other materials provided with the distribution.
* Neither the name of the copyright holder nor the names of its contributors
  may be used to endorse or promote products derived from this software without
  specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```

### Python Software Foundation License Version 2 (PSFL-2.0)
*Applies to Python Standard Library modules.*

```text
PYTHON SOFTWARE FOUNDATION LICENSE VERSION 2
--------------------------------------------
1. This LICENSE AGREEMENT is between the Python Software Foundation ("PSF"), and
   the Individual or Organization ("Licensee") accessing and otherwise using this
   software ("Python") in source or binary form and its associated documentation.

2. Subject to the terms and conditions of this License Agreement, PSF hereby
   grants Licensee a nonexclusive, royalty-free, world-wide license to reproduce,
   analyze, test, perform and/or display publicly, prepare derivative works, distribute,
   and otherwise use Python alone or in any derivative version, provided, however, that
   PSF's License Agreement and PSF's notice of copyright, i.e., "Copyright (c) 2001-2026
   Python Software Foundation; All Rights Reserved" are included in Python alone or
   in any derivative version prepared by Licensee.
```
