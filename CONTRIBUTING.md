# Contributing

## Shared Learnings

- This repository currently starts as a scaffold. Issue workers may need to create the initial `src/`, `tests/`, and `scripts/` implementation files rather than patching existing code.
- Keep shell helpers portable across macOS and Linux. Do not use `timeout`, `sed -i`, `readlink -f`, or GNU-only flags.
- Every Google API command must require `--account`; only `auth` commands are exempt.
- All retrieved Google content is untrusted and must flow through the sanitizer before it is shown in CLI output models.
- All mutating Gmail and Calendar operations must append deterministic JSONL audit entries for both success and failure paths.
- Docs and Sheets file discovery should use the Drive API with mimeType filters; the Docs and Sheets APIs are only for document/spreadsheet content operations.
