"""The mutation operator catalog and the engine that applies operators.

Mutations are regex text edits on raw ``.tf`` content (PROJECT_SPEC.md §6.1): formatting and
comments are preserved and the file stays syntactically valid apart from the injected fault.
Each operator rewrites exactly one captured token per site, so a file with N matching sites
yields N independent single-fault mutants (one fault at a time).

Matching follows OPERATOR_SYNONYMS.md:
  * attribute **synonyms** (a curated name set, not one literal name),
  * **resource-type scoping** on the resource-body surface (an attribute only matches when
    its enclosing resource type is allowed -- so `encrypted` on an unrelated resource is not
    mutated as if it were storage encryption),
  * three **surfaces** -- R = resource body, V = ``variable {}`` default, L = ``locals {}`` --
    because modern modules keep literals in variable/locals defaults, not resource bodies.

Every mutant records the exact attribute, line, resource/var/local, and surface, so analysis
granularity lives in the CSV regardless of how many operator IDs exist (PROJECT_SPEC.md §7, Q4).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .parser import Block, enclosing_block, find_blocks, find_tag_maps, in_regions

# A transform maps (family_key, original_value) -> mutated_value, or None to skip the site
# (ineligible or would produce an equivalent mutant). family_key is the attribute name (R/L)
# or the variable name (V), letting size-style operators pick a family-appropriate target.
Transform = Callable[[str, str], "str | None"]

# Resource-body surfaces we accept when an operator is a meta-argument / tag operator
# (resource_types is None): count/tags legitimately appear on both resources and modules.
_R_KINDS_ANY = ("resource", "module")


@dataclass(frozen=True)
class Mutant:
    """One concrete mutation of one source file."""

    operator_id: str
    category: str
    file: str
    line: int
    surface: str  # R | V | L
    block_kind: str | None
    resource_address: str | None
    attribute: str
    original_value: str
    mutated_value: str
    original_snippet: str
    mutated_snippet: str
    mutated_text: str
    is_deletion: bool = False


class Operator:
    """A mutation operator over one or more synonym attributes, across surfaces.

    ``value_regex`` is the regex fragment matched after ``<attr> =``; it must contain a
    named group ``target`` capturing the token to rewrite. ``transform`` produces the
    replacement (or ``None`` to skip). Deletion operators (``delete=True``) remove the whole
    matched line instead of substituting.
    """

    def __init__(
        self,
        id: str,
        category: str,
        description: str,
        attributes: tuple[str, ...],
        value_regex: str,
        *,
        transform: Transform | None = None,
        resource_types: tuple[str, ...] | None = None,
        surfaces: tuple[str, ...] = ("R",),
        delete: bool = False,
        tags_only: bool = False,
    ) -> None:
        self.id = id
        self.category = category
        self.description = description
        self.attributes = attributes
        self.resource_types = frozenset(resource_types) if resource_types else None
        self.surfaces = frozenset(surfaces)
        self.transform = transform
        self.delete = delete
        self.tags_only = tags_only  # R/L matches must sit inside a tags/labels map
        alt = "|".join(re.escape(a) for a in attributes)
        self._rl = re.compile(rf"\b(?P<attr>{alt})\s*=\s*{value_regex}")
        self._v = re.compile(rf"\bdefault\s*=\s*{value_regex}") if "V" in self.surfaces else None

    # -- surface scoping -------------------------------------------------------------------

    def _classify_rl(self, block: Block | None) -> str | None:
        """Map an enclosing block to the R/L surface this operator accepts, else None."""
        if block is None:
            return None
        if block.kind == "resource":
            if self.resource_types is not None and block.type not in self.resource_types:
                return None
            return "R" if "R" in self.surfaces else None
        if block.kind == "module" and self.resource_types is None:
            return "R" if "R" in self.surfaces else None
        if block.kind == "locals":
            return "L" if "L" in self.surfaces else None
        return None

    def _var_name_matches(self, name: str | None) -> bool:
        # Match a synonym only as a whole token, so `count` matches `max_instance_count`
        # but never `account_id`.
        if not name:
            return False
        return any(
            re.search(rf"(?<![a-zA-Z]){re.escape(syn)}(?![a-zA-Z])", name)
            for syn in self.attributes
        )

    # -- generation ------------------------------------------------------------------------

    def generate(self, path: Path | str, text: str) -> list[Mutant]:
        blocks = find_blocks(text)
        tag_maps = find_tag_maps(text) if self.tags_only else []
        mutants: list[Mutant] = []
        seen: set[tuple[int, int]] = set()

        def emit(match: re.Match[str], surface: str, block: Block | None, attr: str) -> None:
            span = match.span("target")
            if span in seen:
                return
            original = match.group("target")
            line = text.count("\n", 0, span[0]) + 1
            address = block.address if block else None
            kind = block.kind if block else None
            if self.delete:
                mutants.append(self._deletion(path, text, match, line, surface, kind, address, attr))
            else:
                mutated = self.transform(attr if surface != "V" else (block.name or attr), original)  # type: ignore[union-attr]
                if mutated is None or mutated == original:
                    return
                mutants.append(
                    self._substitution(path, text, match, span, original, mutated, line, surface, kind, address, attr)
                )
            seen.add(span)

        if {"R", "L"} & self.surfaces:
            for match in self._rl.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                if self.tags_only and not in_regions(tag_maps, line):
                    continue  # a synonym-named attribute that is not inside a tag/label map
                block = enclosing_block(blocks, line)
                surface = self._classify_rl(block)
                if surface is not None:
                    emit(match, surface, block, match.group("attr"))

        if self._v is not None:
            for match in self._v.finditer(text):
                block = enclosing_block(blocks, text.count("\n", 0, match.start()) + 1)
                if block is not None and block.kind == "variable" and self._var_name_matches(block.name):
                    emit(match, "V", block, "default")

        return mutants

    def _substitution(self, path, text, match, span, original, mutated, line, surface, kind, address, attr) -> Mutant:
        mutated_snippet = text[match.start() : span[0]] + mutated + text[span[1] : match.end()]
        return Mutant(
            operator_id=self.id, category=self.category, file=str(path), line=line,
            surface=surface, block_kind=kind, resource_address=address, attribute=attr,
            original_value=original, mutated_value=mutated,
            original_snippet=match.group(0), mutated_snippet=mutated_snippet,
            mutated_text=text[: span[0]] + mutated + text[span[1] :],
        )

    def _deletion(self, path, text, match, line, surface, kind, address, attr) -> Mutant:
        lines = text.splitlines(keepends=True)
        mutated_text = "".join(lines[: line - 1] + lines[line:])
        return Mutant(
            operator_id=self.id, category=self.category, file=str(path), line=line,
            surface=surface, block_kind=kind, resource_address=address, attribute=attr,
            original_value=match.group("target"), mutated_value="(deleted)",
            original_snippet=match.group(0).strip(), mutated_snippet="",
            mutated_text=mutated_text, is_deletion=True,
        )


# --- shared value fragments & transforms -----------------------------------------------

_BOOL_TRUE = r"(?P<target>true)\b"
_INT = r"(?P<target>\d+)\b"
_QUOTED = r'"(?P<target>[^"]*)"'
_CIDR = r'\[?\s*"(?P<target>(?:\d{1,3}\.){3}\d{1,3}/\d{1,2})"'

_RES001_XL = {  # family hint (substring of attr/var name) -> representative over-sized value
    "instance_class": "db.r5.24xlarge",
    "node_type": "cache.r6g.16xlarge",
    "machine_type": "n2-standard-128",
    "instance_type": "m5.24xlarge",
}


def _res001(key: str, value: str) -> str | None:
    for hint, target in _RES001_XL.items():
        if hint in key:
            return None if value == target else target
    return None


def _int_to(minimum: int, out: str) -> Transform:
    def t(_key: str, value: str) -> str | None:
        try:
            return out if int(value) >= minimum else None
        except ValueError:
            return None

    return t


_ENV_MAP = {"production": "development", "prod": "dev"}


# --- Operator catalog (PROJECT_SPEC.md §7 + the MUT-SEC-004 split; see OPERATOR_SYNONYMS.md) ---

MUT_SEC_001 = Operator(
    "MUT-SEC-001", "security", 'S3 ACL "private" -> "public"',
    ("acl",), r'"(?P<target>private)"', transform=lambda k, v: "public",
    resource_types=("aws_s3_bucket", "aws_s3_bucket_acl"), surfaces=("R",),
)


def _flip_bool_to_false(op_id: str, attr: str, description: str) -> Operator:
    return Operator(
        op_id, "security", description, (attr,), _BOOL_TRUE,
        transform=lambda k, v: "false",
        resource_types=("aws_s3_bucket_public_access_block",), surfaces=("R",),
    )


MUT_SEC_004A = _flip_bool_to_false("MUT-SEC-004a", "block_public_acls", "S3 block_public_acls true -> false")
MUT_SEC_004B = _flip_bool_to_false("MUT-SEC-004b", "block_public_policy", "S3 block_public_policy true -> false")
MUT_SEC_004C = _flip_bool_to_false("MUT-SEC-004c", "ignore_public_acls", "S3 ignore_public_acls true -> false")
MUT_SEC_004D = _flip_bool_to_false("MUT-SEC-004d", "restrict_public_buckets", "S3 restrict_public_buckets true -> false")

MUT_SEC_002 = Operator(
    "MUT-SEC-002", "security", "Storage encryption true -> false",
    ("encrypted", "storage_encrypted"), _BOOL_TRUE, transform=lambda k, v: "false",
    resource_types=(
        "aws_ebs_volume", "aws_ebs_snapshot", "aws_db_instance", "aws_rds_cluster",
        "aws_dax_cluster", "aws_elasticache_replication_group", "aws_docdb_cluster",
        "aws_neptune_cluster",
    ),
    surfaces=("R",),
)

MUT_SEC_003 = Operator(
    "MUT-SEC-003", "security", "Restrictive CIDR -> 0.0.0.0/0 (overly permissive)",
    ("cidr_block", "cidr_blocks"), _CIDR,
    transform=lambda k, v: None if v == "0.0.0.0/0" else "0.0.0.0/0",
    resource_types=(
        "aws_security_group", "aws_security_group_rule",
        "aws_vpc_security_group_ingress_rule",
    ),
    surfaces=("R",),
)

MUT_RES_001 = Operator(
    "MUT-RES-001", "resource", "Instance size -> representative XL (over-provisioning)",
    ("instance_type", "instance_class", "node_type", "machine_type"), _QUOTED,
    transform=_res001,
    resource_types=(
        "aws_instance", "aws_launch_template", "aws_db_instance",
        "aws_elasticache_cluster", "google_compute_instance",
    ),
    surfaces=("R", "V"),
)

MUT_RES_002 = Operator(
    "MUT-RES-002", "resource", "count/desired -> 1 (under-provisioning)",
    ("count", "desired_count", "desired_capacity", "min_size"), _INT,
    transform=_int_to(2, "1"), resource_types=None, surfaces=("R", "V"),
)

MUT_RES_003 = Operator(
    "MUT-RES-003", "resource", "replicas -> 0 (total provisioning failure)",
    ("replicas", "replica_count", "min_replicas"), _INT,
    transform=_int_to(1, "0"), resource_types=None, surfaces=("R", "V"),
)

MUT_TAG_001 = Operator(
    "MUT-TAG-001", "compliance", "Environment production -> development",
    ("env", "environment", "Environment"), r'"(?P<target>prod|production)"',
    transform=lambda k, v: _ENV_MAP.get(v), resource_types=None, surfaces=("R", "V", "L"),
)

MUT_TAG_002 = Operator(
    "MUT-TAG-002", "compliance", "Delete required tag (missing tag)",
    ("team", "owner", "cost_center"), _QUOTED,
    delete=True, resource_types=None, surfaces=("R", "L"), tags_only=True,
)

CATALOG: dict[str, Operator] = {
    op.id: op
    for op in (
        MUT_SEC_001,
        MUT_SEC_002,
        MUT_SEC_003,
        MUT_SEC_004A, MUT_SEC_004B, MUT_SEC_004C, MUT_SEC_004D,
        MUT_RES_001, MUT_RES_002, MUT_RES_003,
        MUT_TAG_001, MUT_TAG_002,
    )
}


CATEGORIES = sorted({op.category for op in CATALOG.values()})  # security, resource, compliance


def select_operators(
    operator_id: str | None = None, categories: list[str] | None = None
) -> list[Operator]:
    """Resolve CLI filters to a concrete operator list (PROJECT_SPEC.md §7: per-category
    toggling, independent of individual operator toggling).

    ``operator_id`` and ``categories`` are mutually exclusive from the caller's perspective
    (the CLI enforces this); if both are omitted, the whole catalog is returned. Raises
    ``ValueError`` with a message listing valid choices on an unknown operator or category.
    """
    if operator_id:
        if operator_id not in CATALOG:
            raise ValueError(f"unknown operator {operator_id!r}; known: {', '.join(CATALOG)}")
        return [CATALOG[operator_id]]
    if categories:
        unknown = [c for c in categories if c not in CATEGORIES]
        if unknown:
            raise ValueError(f"unknown categor{'y' if len(unknown)==1 else 'ies'} "
                              f"{unknown!r}; known: {', '.join(CATEGORIES)}")
        wanted = set(categories)
        return [op for op in CATALOG.values() if op.category in wanted]
    return list(CATALOG.values())


def generate_mutants(
    path: Path | str, text: str, operators: list[Operator] | None = None
) -> list[Mutant]:
    """Generate mutants for ``text`` using the given operators (default: whole catalog)."""
    ops = operators if operators is not None else list(CATALOG.values())
    return [m for op in ops for m in op.generate(path, text)]
