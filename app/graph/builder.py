from typing import Any


 

from langgraph.graph import END, START, StateGraph


 

from app.graph.nodes.analysis_nodes import AnalysisNodeDependencies, AnalysisNodes

from app.graph.state import AnalysisState



 

def build_analysis_graph(

    *,

    dependencies: AnalysisNodeDependencies,

    checkpointer: Any,

):

    nodes = AnalysisNodes(dependencies)

    builder = StateGraph(AnalysisState)


 

    builder.add_node("normalize_request", nodes.normalize_request)

    builder.add_node("load_schema", nodes.load_schema)

    builder.add_node("resolve_business_terms", nodes.resolve_business_terms)

    builder.add_node("request_clarification", nodes.request_clarification)

    builder.add_node("apply_clarification", nodes.apply_clarification)

    builder.add_node("create_analysis_plan", nodes.create_analysis_plan)

    builder.add_node("generate_sql", nodes.generate_sql)

    builder.add_node("execute_sql", nodes.execute_sql)

    builder.add_node("repair_sql", nodes.repair_sql)

    builder.add_node("summarize_result", nodes.summarize_result)

    builder.add_node("finalize_success", nodes.finalize_success)

    builder.add_node("finalize_failure", nodes.finalize_failure)


 

    builder.add_edge(START, "normalize_request")

    builder.add_conditional_edges(

        "normalize_request",

        nodes.route_after_intake,

        {"continue": "load_schema", "stop": "finalize_failure"},

    )

    builder.add_edge("load_schema", "resolve_business_terms")

    builder.add_conditional_edges(

        "resolve_business_terms",

        nodes.route_after_terms,

        {"clarify": "request_clarification", "plan": "create_analysis_plan"},

    )

    builder.add_edge("request_clarification", "apply_clarification")

    builder.add_edge("apply_clarification", "create_analysis_plan")

    builder.add_edge("create_analysis_plan", "generate_sql")

    builder.add_edge("generate_sql", "execute_sql")

    builder.add_conditional_edges(

        "execute_sql",

        nodes.route_after_execution,

        {

            "summarize": "summarize_result",

            "repair": "repair_sql",

            "stop": "finalize_failure",

        },

    )

    builder.add_edge("repair_sql", "execute_sql")

    builder.add_edge("summarize_result", "finalize_success")

    builder.add_edge("finalize_success", END)

    builder.add_edge("finalize_failure", END)


 

    return builder.compile(checkpointer=checkpointer)


 