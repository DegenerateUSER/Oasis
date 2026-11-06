# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

User delegated the recommendation and approved React/TypeScript packaged with the existing Python CLI. Local-only browser UI; no hosted service or login. Use the existing verified execution and metrics contracts instead of a second mutation engine.

## Users

Tushar, developing and evaluating Oasis. The audience and job are grounded in the existing project: inspecting infrastructure-as-code mutation testing results and operating bounded local evaluations.

## Product Purpose

Oasis evaluates the semantic quality of Terraform/OpenTofu test suites using precise source mutations. The GUI makes local configuration, execution, progress, evidence and analytics accessible without replacing the CLI.

## Operating Context

Local repositories, installed Terraform/OpenTofu, CSV/JSON completion artifacts, diagnostic logs and historical benchmark CSVs. No cloud account or hosted deployment is part of the GUI delivery.

## Capabilities and Constraints

Confirmed scope: configure and launch bounded runs, observe progress, inspect mutants/logs, import results and explore analytics. Preserve all verified hardening in commit 65778f2. Use shared metrics with separate assertion kills, engine-error kills, survivors and exclusions. A missing denominator is not zero percent. Historical imports must not be presented as verified reruns. Do not execute the full corpus during development. Preserve original checkout edits. Single active job to fit the user's machine. No paid services or paid media generation.

## Brand Commitments

Product name Oasis. User explicitly requested both the local Impeccable and Apple-design skills. Plain, precise developer-facing language; retain native/familiar interaction expectations.

## Evidence on Hand

Existing benchmark CSVs are historical data, not fresh evaluations. Verified tiny-run artifacts and regression suite are available in the hardening report directory. No fabricated score, trend, runtime coverage or full-corpus validation claim is allowed.

## Product Principles

- Evidence before confidence: show provenance and uncertainty.
- Safe local control: explicit bounded execution, single active job and no arbitrary shell command field.
- One scoring contract across CLI and GUI.
- Keep the CLI install useful without Node at runtime.
