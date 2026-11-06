# Oasis local GUI

The Signal workspace runs in your browser on loopback and uses the same mutation execution, scoring and artifact-verification code as the CLI. It is not a hosted service and has no user accounts.

## Launch

From a source checkout with the packaged frontend built:

```sh
uv sync --locked
uv run oasis gui
```

To choose a port/state directory without opening a browser automatically:

```sh
uv run oasis gui --no-open --port 8765 \
  --data-dir "$HOME/.local/share/oasis/gui"
```

The server prints its local address. It only accepts loopback hosts; exposing it publicly is not supported. Compiled assets ship inside the Python package, so normal use does not require Node. A source build without compiled frontend assets reports that requirement explicitly rather than showing an empty page.

## Understand results

- Import your own result CSV or use the registered historical CSV when running from this repository. A standalone installed wheel may have no bundled historical source; import a CSV instead.
- Historical and uploaded CSVs are not independently verified reruns. Their provenance remains visible even when the rows look plausible.
- Local completed jobs publish a dataset only after the completed manifest, CSV, summary and raw evidence pass integrity checks. Later tampering removes the verified label and log access.
- Mutation score includes assertion kills and engine-error kills; assertion score shows assertion kills separately. Both use only the shared allowlisted scored outcomes.
- Invalid, timeout, no-op, unknown, unresolved and unexecuted outcomes remain inspectable but excluded. A zero denominator displays no score, not zero percent.
- Chart selections and repository/category/operator/outcome/search filters affect the underlying records and server-generated summary together. Filtered CSV exports use the same selection; an unfiltered CSV export preserves original contents.
- A static survivor explanation is not runtime coverage and is not proof of semantic equivalence. Old classifications are not revalidated by displaying them.
- Timings appear only when the imported/run data actually includes them. No invented historical trend is generated.

## Run a trusted local repository

Use a committed repository with selected `.tftest.hcl` files. Choose Terraform or OpenTofu, operators and a bounded mutant count/wall-clock budget. Preview is read-only lexical discovery; it does not initialize providers, validate native syntax or execute tests.

Starting execution requires explicit acknowledgement: Terraform tests and providers can execute local code, read environment credentials, contact networks and create cloud resources. Oasis is not a sandbox. Prefer plan-only fixtures or mocked providers for development and review repositories before running them.

The default GUI limits are 20 mutants and 120 seconds, with a 30-second command/init timeout and one init attempt. The server validates configured upper bounds. The GUI launches a single repository job, not an implicit corpus batch.

Progress reports completed commands, current phase and elapsed time; it does not invent a completion percentage when the total is unknown. Cancellation is a request until confirmed. The isolated worker receives SIGINT so restoration can run, and the GUI never escalates to SIGKILL while source restoration may be in progress. After restoration, remaining owned same-process-group descendants are drained with TERM and, when necessary, bounded KILL escalation; the Python restoration worker is excluded. Execution ownership is retained until cleanup is confirmed. Inspection failures remain explicit and block new work rather than being reported as clean cancellation. Code that deliberately escapes its process group is outside this boundary; Oasis is not a sandbox. Do not edit the target repository or run another tool against it during a job.

A restart marks abandoned jobs interrupted. SIGKILL, power loss and machine failure cannot guarantee restoration; inspect the repository before rerunning. Native locking/signals currently target POSIX/macOS; Windows GUI execution is not supported by this implementation.

## Privacy and access controls

State is stored in a private local directory outside the target repository. API requests require a per-server random session token and same-origin loopback Host/Origin checks. Arbitrary executable commands are not accepted. Uploaded CSV log paths are never trusted as filesystem-read authority. Raw-log access is restricted to exact, verified, job-owned evidence.

The service is for one local trusted user, not multi-tenant hosting. It is not a replacement for operating-system isolation. Logs may contain output from your own tests/providers; handle the state directory accordingly.

## Frontend development

The React/TypeScript application lives under `frontend/`. Its production build writes to `src/tfmutate/gui/static/`; those assets are included in the wheel. Build and test scripts are documented in the frontend package. Run only one frontend build/browser on memory-constrained machines.

## Evaluation boundary

The GUI does not automatically rerun or validate the historical corpus. A full-corpus evaluation is a separate, explicitly authorized task. Do not cite a displayed historical result as a new verified experiment.
