# vNext delivery inventory gate v1

This read-only gate checks the exact file lists in
`contracts/vnext_requirements_v1.json`: all required JSON, JSONL and Markdown
files must exist, be nonempty and parse correctly. It names absent/invalid
files and flags NOT_RUN in the final end-to-end and decision documents. It
never writes placeholders or opens the private blind-label file.

`complete_artifact_inventory=true` means only that the named files exist and
parse. It does NOT prove that the Core was executed, certificates are valid,
docs agree with machine results, final SHA-256 manifest matches, the provider
gate passed, or any promotion threshold was met. Those are separate mandatory
audits. This checker cannot make a partial experiment look complete merely by
finding well-formed JSON.
