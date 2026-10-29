from collections.abc import Iterable

from typing import Any


 

import sqlglot

from sqlglot import exp

from sqlglot.errors import ParseError


 

from app.sql.models import SqlValidationResult, ValidationIssue

from app.sql.policy import SqlPolicy



 

_BLOCKED_EXPRESSION_CLASS_NAMES = {

    "Alter",

    "Analyze",

    "Attach",

    "Cache",

    "Call",

    "Command",

    "Commit",

    "Copy",

    "Create",

    "Delete",

    "Detach",

    "Drop",

    "Execute",

    "Export",

    "Grant",

    "Import",

    "Insert",

    "Into",

    "LoadData",

    "Lock",

    "Merge",

    "Pragma",

    "Prepare",

    "Refresh",

    "Replace",

    "Revoke",

    "Rollback",

    "Set",

    "Show",

    "Transaction",

    "TruncateTable",

    "Uncache",

    "Update",

    "Use",

    "Vacuum",

}


 

_BLOCKED_EXPRESSION_KEYS = {

    "alter",

    "analyze",

    "attach",

    "cache",

    "call",

    "command",

    "commit",

    "copy",

    "create",

    "delete",

    "detach",

    "drop",

    "execute",

    "export",

    "grant",

    "import",

    "insert",

    "into",

    "load_data",

    "lock",

    "merge",

    "pragma",

    "prepare",

    "refresh",

    "replace",

    "revoke",

    "rollback",

    "set",

    "show",

    "transaction",

    "truncate_table",

    "uncache",

    "update",

    "use",

    "vacuum",

}



 

class SqlValidator:

    def __init__(self, policy: SqlPolicy) -> None:

        self.policy = policy


 

    def validate(self, sql: str) -> SqlValidationResult:

        issues: list[ValidationIssue] = []

        source_sql = sql.strip()


 

        if not source_sql:

            return self._rejected("EMPTY_SQL", "SQL cannot be empty.")


 

        if len(source_sql) > self.policy.max_sql_length:

            return self._rejected(

                "SQL_TOO_LONG",

                f"SQL exceeds the {self.policy.max_sql_length}-character limit.",

            )


 

        try:

            statements = [

                statement

                for statement in sqlglot.parse(source_sql, read=self.policy.dialect)

                if statement is not None

            ]

        except ParseError as exc:

            detail = self._parse_error_message(exc)

            return self._rejected("SQL_PARSE_ERROR", detail)


 

        if len(statements) != 1:

            return self._rejected(

                "SINGLE_STATEMENT_REQUIRED",

                "Exactly one SQL statement is allowed.",

            )


 

        statement = statements[0]

        query_type = getattr(exp, "Query", None)

        if query_type is None or not isinstance(statement, query_type):

            issues.append(

                ValidationIssue(

                    code="READ_QUERY_REQUIRED",

                    message=(

                        "Only SELECT, WITH ... SELECT, UNION, INTERSECT, or EXCEPT "

                        "queries are allowed."

                    ),

                )

            )


 

        nodes = list(self._walk_nodes(statement))

        self._check_blocked_nodes(nodes, issues)

        self._check_recursive_cte(statement, issues)


 

        cte_names = self._cte_names(statement)

        tables = self._check_tables(statement, cte_names, issues)

        functions = self._check_functions(statement, issues)

        self._check_denied_columns(statement, issues)

        self._check_select_star(statement, issues)


 

        join_count = self._check_joins(statement, issues)

        subquery_depth = self._max_query_depth(nodes)

        if subquery_depth > self.policy.max_subquery_depth:

            issues.append(

                ValidationIssue(

                    code="SUBQUERY_DEPTH_EXCEEDED",

                    message=(

                        f"Query nesting depth {subquery_depth} exceeds the allowed maximum "

                        f"of {self.policy.max_subquery_depth}."

                    ),

                )

            )


 

        requested_limit = self._read_nonnegative_integer_clause(

            statement.args.get("limit"),

            clause_name="LIMIT",

            issues=issues,

        )

        offset = self._read_nonnegative_integer_clause(

            statement.args.get("offset"),

            clause_name="OFFSET",

            issues=issues,

        )

        if offset is not None and offset > self.policy.max_offset:

            issues.append(

                ValidationIssue(

                    code="OFFSET_TOO_LARGE",

                    message=(

                        f"OFFSET {offset} exceeds the allowed maximum of "

                        f"{self.policy.max_offset}."

                    ),

                )

            )


 

        accepted = not any(issue.severity == "error" for issue in issues)

        normalized_sql = statement.sql(dialect=self.policy.dialect, pretty=True)


 

        executable_sql: str | None = None

        enforced_limit: int | None = None

        truncation_probe_enabled = False


 

        if accepted:

            executable_tree = statement.copy()

            safe_row_cap = self.policy.max_result_rows + self.policy.fetch_probe_rows


 

            if requested_limit is None:

                executable_tree = executable_tree.limit(safe_row_cap, copy=False)

                enforced_limit = safe_row_cap

                truncation_probe_enabled = self.policy.fetch_probe_rows > 0

                issues.append(

                    ValidationIssue(

                        code="ROW_LIMIT_INJECTED",

                        message=f"QueryGuard added LIMIT {safe_row_cap} to enforce the row cap.",

                        severity="warning",

                    )

                )

            elif requested_limit > self.policy.max_result_rows:

                executable_tree = executable_tree.limit(safe_row_cap, copy=False)

                enforced_limit = safe_row_cap

                truncation_probe_enabled = self.policy.fetch_probe_rows > 0

                issues.append(

                    ValidationIssue(

                        code="ROW_LIMIT_CLAMPED",

                        message=(

                            f"Requested LIMIT {requested_limit} was reduced to an internal "

                            f"limit of {safe_row_cap}; no more than "

                            f"{self.policy.max_result_rows} rows will be returned."

                        ),

                        severity="warning",

                    )

                )

            else:

                enforced_limit = requested_limit


 

            executable_sql = executable_tree.sql(dialect=self.policy.dialect, pretty=False)


 

        return SqlValidationResult(

            accepted=accepted,

            normalized_sql=normalized_sql,

            executable_sql=executable_sql,

            tables=sorted(tables),

            functions=sorted(functions),

            join_count=join_count,

            subquery_depth=subquery_depth,

            requested_limit=requested_limit,

            enforced_limit=enforced_limit,

            truncation_probe_enabled=truncation_probe_enabled,

            issues=issues,

        )


 

    @staticmethod

    def _walk_nodes(statement: exp.Expression) -> Iterable[exp.Expression]:

        for item in statement.walk():

            # SQLGlot's older releases yielded (node, parent, key) tuples.

            node = item[0] if isinstance(item, tuple) else item

            if isinstance(node, exp.Expression):

                yield node


 

    @staticmethod

    def _parse_error_message(exc: ParseError) -> str:

        errors = getattr(exc, "errors", None)

        if errors:

            first = errors[0]

            description = first.get("description", "Invalid SQL syntax")

            line = first.get("line")

            column = first.get("col")

            if line is not None and column is not None:

                return f"{description} at line {line}, column {column}."

            return f"{description}."

        return "The SQL parser rejected the statement."


 

    @staticmethod

    def _rejected(code: str, message: str) -> SqlValidationResult:

        return SqlValidationResult(

            accepted=False,

            issues=[ValidationIssue(code=code, message=message)],

        )


 

    @staticmethod

    def _check_blocked_nodes(

        nodes: list[exp.Expression],

        issues: list[ValidationIssue],

    ) -> None:

        blocked: set[str] = set()

        for node in nodes:

            class_name = node.__class__.__name__

            key = str(getattr(node, "key", "")).lower()

            if class_name in _BLOCKED_EXPRESSION_CLASS_NAMES or key in _BLOCKED_EXPRESSION_KEYS:

                blocked.add(class_name)


 

            # PostgreSQL row-locking clauses such as FOR UPDATE and FOR SHARE.

            if class_name == "ForClause" or key == "for_clause":

                blocked.add("ForClause")


 

        if blocked:

            issues.append(

                ValidationIssue(

                    code="BLOCKED_SQL_OPERATION",

                    message=(

                        "The query contains blocked SQL operation(s): "

                        + ", ".join(sorted(blocked))

                        + "."

                    ),

                )

            )


 

    def _check_recursive_cte(

        self,

        statement: exp.Expression,

        issues: list[ValidationIssue],

    ) -> None:

        with_type = getattr(exp, "With", None)

        if with_type is None:

            return


 

        for with_node in statement.find_all(with_type):

            recursive = bool(getattr(with_node, "recursive", False)) or bool(

                with_node.args.get("recursive")

            )

            if recursive and not self.policy.allow_recursive_cte:

                issues.append(

                    ValidationIssue(

                        code="RECURSIVE_CTE_NOT_ALLOWED",

                        message="WITH RECURSIVE is not allowed in Phase 2.",

                    )

                )


 

    @staticmethod

    def _cte_names(statement: exp.Expression) -> set[str]:

        cte_type = getattr(exp, "CTE", None)

        if cte_type is None:

            return set()

        return {

            cte.alias_or_name.lower()

            for cte in statement.find_all(cte_type)

            if cte.alias_or_name

        }


 

    def _check_tables(

        self,

        statement: exp.Expression,

        cte_names: set[str],

        issues: list[ValidationIssue],

    ) -> set[str]:

        tables: set[str] = set()

        table_type = getattr(exp, "Table", None)

        if table_type is None:

            return tables


 

        for table in statement.find_all(table_type):

            name = (getattr(table, "name", "") or "").lower()

            schema = (getattr(table, "db", "") or "").lower()

            catalog = (getattr(table, "catalog", "") or "").lower()


 

            if not schema and name in cte_names:

                continue


 

            if catalog:

                issues.append(

                    ValidationIssue(

                        code="CATALOG_NOT_ALLOWED",

                        message=f"Catalog-qualified table access is not allowed: {table.sql()}.",

                    )

                )

                continue


 

            if self.policy.require_schema_qualification and not schema:

                issues.append(

                    ValidationIssue(

                        code="SCHEMA_QUALIFICATION_REQUIRED",

                        message=(

                            f"Table '{name}' must be schema-qualified, for example "

                            f"analytics.{name}."

                        ),

                    )

                )

                continue


 

            fully_qualified = f"{schema}.{name}" if schema else name

            tables.add(fully_qualified)


 

            if schema and schema not in self.policy.allowed_schemas:

                issues.append(

                    ValidationIssue(

                        code="SCHEMA_NOT_ALLOWED",

                        message=f"Schema '{schema}' is not allowed.",

                    )

                )

            elif fully_qualified not in self.policy.allowed_tables:

                issues.append(

                    ValidationIssue(

                        code="TABLE_NOT_ALLOWED",

                        message=f"Table or view '{fully_qualified}' is not on the allowlist.",

                    )

                )


 

        return tables


 

    def _check_functions(

        self,

        statement: exp.Expression,

        issues: list[ValidationIssue],

    ) -> set[str]:

        functions: set[str] = set()

        function_type = getattr(exp, "Func", None)

        if function_type is None:

            return functions


 

        for function in statement.find_all(function_type):

            if isinstance(function,(exp.And,exp.Or,exp.Not)):

                continue

            function_name = self._function_name(function)

            if not function_name:

                continue

            functions.add(function_name)


 

            if function_name in self.policy.denied_functions:

                issues.append(

                    ValidationIssue(

                        code="FUNCTION_DENIED",

                        message=f"Function '{function_name}' is explicitly denied.",

                    )

                )

            elif (

                self.policy.function_policy == "allowlist"

                and function_name not in self.policy.allowed_functions

            ):

                issues.append(

                    ValidationIssue(

                        code="FUNCTION_NOT_ALLOWED",

                        message=f"Function '{function_name}' is not on the allowlist.",

                    )

                )


 

        return functions


 

    @staticmethod

    def _function_name(function: Any) -> str:

        name = ""

        try:

            name = str(function.sql_name())

        except (AttributeError, TypeError):

            name = ""


 

        if not name or name.upper() == "ANONYMOUS":

            name = str(getattr(function, "name", "") or getattr(function, "key", ""))

        return name.upper()


 

    def _check_denied_columns(

        self,

        statement: exp.Expression,

        issues: list[ValidationIssue],

    ) -> None:

        column_type = getattr(exp, "Column", None)

        if column_type is None:

            return


 

        denied_found = {

            column.name.lower()

            for column in statement.find_all(column_type)

            if column.name and column.name.lower() in self.policy.denied_columns

        }

        if denied_found:

            issues.append(

                ValidationIssue(

                    code="PII_COLUMN_DENIED",

                    message=(

                        "The query references denied column name(s): "

                        + ", ".join(sorted(denied_found))

                        + "."

                    ),

                )

            )


 

    def _check_select_star(

        self,

        statement: exp.Expression,

        issues: list[ValidationIssue],

    ) -> None:

        if not self.policy.forbid_select_star:

            return


 

        select_type = getattr(exp, "Select", None)

        alias_type = getattr(exp, "Alias", None)

        if select_type is None:

            return


 

        for select in statement.find_all(select_type):

            for projection in select.expressions:

                candidate = (

                    projection.this

                    if alias_type is not None and isinstance(projection, alias_type)

                    else projection

                )

                if bool(getattr(candidate, "is_star", False)):

                    issues.append(

                        ValidationIssue(

                            code="SELECT_STAR_NOT_ALLOWED",

                            message=(

                                "SELECT * and table.* are not allowed; list the required "

                                "columns."

                            ),

                        )

                    )

                    return


 

    def _check_joins(

        self,

        statement: exp.Expression,

        issues: list[ValidationIssue],

    ) -> int:

        join_type = getattr(exp, "Join", None)

        if join_type is None:

            return 0


 

        joins = list(statement.find_all(join_type))

        if len(joins) > self.policy.max_joins:

            issues.append(

                ValidationIssue(

                    code="JOIN_LIMIT_EXCEEDED",

                    message=(

                        f"Query has {len(joins)} joins; the maximum is {self.policy.max_joins}."

                    ),

                )

            )


 

        for join in joins:

            kind = str(getattr(join, "kind", "") or "").upper()

            method = str(getattr(join, "method", "") or "").upper()

            if kind == "CROSS" and not self.policy.allow_cross_join:

                issues.append(

                    ValidationIssue(

                        code="CROSS_JOIN_NOT_ALLOWED",

                        message="CROSS JOIN is not allowed.",

                    )

                )


 

            if method == "NATURAL":

                issues.append(

                    ValidationIssue(

                        code="NATURAL_JOIN_NOT_ALLOWED",

                        message=(

                            "NATURAL JOIN is not allowed; use an explicit ON or USING "

                            "condition."

                        ),

                    )

                )


 

            if (

                self.policy.require_join_condition

                and kind != "CROSS"

                and method != "NATURAL"

                and join.args.get("on") is None

                and not join.args.get("using")

            ):

                issues.append(

                    ValidationIssue(

                        code="JOIN_CONDITION_REQUIRED",

                        message="Every JOIN must include an explicit ON or USING condition.",

                    )

                )


 

        return len(joins)


 

    @staticmethod

    def _max_query_depth(nodes: list[exp.Expression]) -> int:

        query_type = getattr(exp, "Query", None)

        if query_type is None:

            return 0


 

        max_depth = 0

        for node in nodes:

            if not isinstance(node, query_type):

                continue

            depth = 1

            parent = node.parent

            while parent is not None:

                if isinstance(parent, query_type):

                    depth += 1

                parent = parent.parent

            max_depth = max(max_depth, depth)

        return max_depth


 

    @staticmethod

    def _read_nonnegative_integer_clause(

        clause: exp.Expression | None,

        *,

        clause_name: str,

        issues: list[ValidationIssue],

    ) -> int | None:

        if clause is None:

            return None


 

        limit_options = clause.args.get("limit_options")

        if limit_options is not None:

            if limit_options.args.get("percent") or limit_options.args.get("with_ties"):

                issues.append(

                    ValidationIssue(

                        code=f"UNSUPPORTED_{clause_name}_OPTION",

                        message=f"{clause_name} PERCENT and WITH TIES are not allowed.",

                    )

                )


 

        value_expression = clause.args.get("expression")

        if value_expression is None:

            issues.append(

                ValidationIssue(

                    code=f"INVALID_{clause_name}",

                    message=f"{clause_name} must contain a non-negative integer literal.",

                )

            )

            return None


 

        is_int = bool(getattr(value_expression, "is_int", False))

        if not is_int:

            issues.append(

                ValidationIssue(

                    code=f"NON_LITERAL_{clause_name}",

                    message=f"{clause_name} must be a non-negative integer literal.",

                )

            )

            return None


 

        try:

            value = int(value_expression.this)

        except (TypeError, ValueError):

            issues.append(

                ValidationIssue(

                    code=f"INVALID_{clause_name}",

                    message=f"{clause_name} must be a non-negative integer literal.",

                )

            )

            return None


 

        if value < 0:

            issues.append(

                ValidationIssue(

                    code=f"NEGATIVE_{clause_name}",

                    message=f"{clause_name} cannot be negative.",

                )

            )

            return None

        return value


 