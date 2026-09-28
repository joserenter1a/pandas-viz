"""Pydantic schemas shared by the tracer, the API and (via OpenAPI) the frontend."""

from typing import Any, Literal

from pydantic import BaseModel, Field

Category = Literal[
    "source", "filter", "projection", "join", "aggregate",
    "sort", "limit", "reshape", "mutate", "other",
]


class ColumnInfo(BaseModel):
    name: str
    dtype: str
    null_count: int
    n_unique: int | None = None


class FrameProfile(BaseModel):
    kind: Literal["DataFrame", "Series"]
    rows: int
    cols: int
    memory_bytes: int
    columns: list[ColumnInfo]
    index: list[str]
    sample_columns: list[str]
    sample: list[list[Any]]
    sample_index: list[Any]


ExampleKind = Literal[
    "dropped", "unmatched_left", "unmatched_right", "duplicate_keys_left",
    "duplicate_keys_right", "null_keys_left", "null_keys_right", "nulls",
]


class RowExamples(BaseModel):
    """A few concrete rows illustrating what an operation lost, duplicated or nulled."""
    kind: ExampleKind
    label: str
    total: int  # how many rows are in this category (only a few are kept)
    column: str | None = None  # for "nulls": the column that became null
    highlight: list[str] = Field(default_factory=list)  # e.g. join keys
    columns: list[str]
    index: list[Any]
    rows: list[list[Any]]


class SchemaChange(BaseModel):
    added: list[str] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)
    dtype_changed: dict[str, tuple[str, str]] = Field(default_factory=dict)


class Node(BaseModel):
    id: str
    op: str
    category: Category
    label: str
    var_name: str | None = None
    source_line: int | None = None
    source_text: str | None = None
    args: dict[str, str] = Field(default_factory=dict)
    profile: FrameProfile
    duration_ms: float = 0.0
    rows_in: int | None = None
    schema_change: SchemaChange | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    examples: list[RowExamples] = Field(default_factory=list)


class Edge(BaseModel):
    source: str
    target: str
    role: Literal["input", "left", "right", "other"] = "input"


class Finding(BaseModel):
    kind: Literal["row_loss", "row_explosion", "null_origin", "dtype_drift", "join"]
    severity: Literal["info", "warning", "error"]
    node_id: str
    message: str
    column: str | None = None
    example_kind: ExampleKind | None = None  # rows on the node's `examples` that illustrate it


class Hint(BaseModel):
    """An optimization that keeps the result the same (pushdowns, anti-patterns)."""
    kind: Literal["filter_before_join", "filter_earlier", "unused_columns", "useless_sort",
                  "row_apply", "duplicate_read", "inplace"]
    node_id: str
    message: str
    suggestion: str | None = None
    related: list[str] = Field(default_factory=list)  # other steps involved


class Check(BaseModel):
    node_id: str
    kind: Literal["merge_validate", "row_count", "not_null", "not_empty", "dtype", "schema", "pandera"]
    line: int | None = None
    # "replace": code is the edited call on `line`; otherwise an assert to put before/after it
    position: Literal["before", "after", "replace"]
    code: str
    passes: bool
    reason: str


class TraceError(BaseModel):
    type: str
    message: str
    line: int | None = None
    traceback: str


class ColumnDiff(BaseModel):
    name: str
    status: Literal["added", "removed", "renamed", "changed", "same"]
    renamed_from: str | None = None
    dtype_a: str | None = None
    dtype_b: str | None = None
    nulls_a: int | None = None
    nulls_b: int | None = None
    unique_a: int | None = None
    unique_b: int | None = None


class PathStep(BaseModel):
    node_id: str
    op: str
    label: str
    var_name: str | None = None
    rows: int


class NodeDiff(BaseModel):
    a: str
    b: str
    # "ancestor": a feeds into b; "descendant": b feeds into a
    relation: Literal["same", "ancestor", "descendant", "unrelated"]
    path: list[PathStep] = Field(default_factory=list)  # earlier node → later node
    rows_a: int
    rows_b: int
    cols_a: int
    cols_b: int
    memory_a: int
    memory_b: int
    index_a: list[str]
    index_b: list[str]
    columns: list[ColumnDiff]


class TraceResult(BaseModel):
    nodes: list[Node] = Field(default_factory=list)
    edges: list[Edge] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    hints: list[Hint] = Field(default_factory=list)
    checks: list[Check] = Field(default_factory=list)
    checks_script: str = ""
    stdout: str = ""
    error: TraceError | None = None
    warnings: list[str] = Field(default_factory=list)

    def examples_for(self, finding: Finding) -> "RowExamples | None":
        """The example rows that illustrate ``finding``, if the trace kept any."""
        if finding.example_kind is None:
            return None
        node = next((n for n in self.nodes if n.id == finding.node_id), None)
        for ex in node.examples if node else []:
            if ex.kind == finding.example_kind and (ex.kind != "nulls" or ex.column == finding.column):
                return ex
        return None

    def node(self, ref: str) -> Node:
        """Look up a node by id (``"n3"``) or variable name (the last node bound to it)."""
        for n in self.nodes:
            if n.id == ref:
                return n
        named = [n for n in self.nodes if n.var_name == ref]
        if not named:
            raise KeyError(f"no node with id or variable name {ref!r}")
        return named[-1]

    def diff(self, a: str, b: str) -> "NodeDiff":
        """Compare two steps (ids or variable names): rows, columns, dtypes, nulls, path."""
        from .diff import diff_nodes

        return diff_nodes(self, self.node(a).id, self.node(b).id)


class DatasetInfo(BaseModel):
    name: str  # the variable name it is available as in traced code
    filename: str
    format: Literal["csv", "tsv", "parquet", "json", "jsonl"]
    size_bytes: int
    rows: int
    cols: int
    columns: list[ColumnInfo]
    uploaded_at: str


class DiffRequest(BaseModel):
    trace: TraceResult
    a: str
    b: str


class TraceRequest(BaseModel):
    code: str
    timeout_s: float = 30.0


class Example(BaseModel):
    id: str
    title: str
    description: str
    code: str


class TraceSummary(BaseModel):
    id: str
    title: str
    created_at: str
    n_nodes: int
    n_findings: int
    has_error: bool


class StoredTrace(TraceSummary):
    code: str
    result: TraceResult
