from pathlib import Path


 

import yaml


 

from app.catalog.models import (

    BusinessTermDefinition,

    DimensionDefinition,

    MetricDefinition,

    SemanticCatalog,

)



 

def _load_yaml(path: str | Path) -> dict:

    path = Path(path)

    if not path.exists():

        raise FileNotFoundError(f"Catalog file not found: {path}")

    with path.open("r", encoding="utf-8") as file:

        return yaml.safe_load(file) or {}



 

def load_semantic_catalog(

    *,

    metrics_path: str | Path,

    dimensions_path: str | Path,

    business_terms_path: str | Path,

) -> SemanticCatalog:

    metrics_raw = _load_yaml(metrics_path)

    dimensions_raw = _load_yaml(dimensions_path)

    terms_raw = _load_yaml(business_terms_path)


 

    metrics = {

        metric_id: MetricDefinition(metric_id=metric_id, **definition)

        for metric_id, definition in (metrics_raw.get("metrics") or {}).items()

    }

    dimensions = {

        dimension_id: DimensionDefinition(dimension_id=dimension_id, **definition)

        for dimension_id, definition in (dimensions_raw.get("dimensions") or {}).items()

    }

    terms = {

        term: BusinessTermDefinition(term=term, **definition)

        for term, definition in (terms_raw.get("terms") or {}).items()

    }


 

    if not metrics:

        raise ValueError("The metric catalog is empty.")

    if not dimensions:

        raise ValueError("The dimension catalog is empty.")


 

    return SemanticCatalog(

        version=int(metrics_raw.get("version", 1)),

        business_timezone=str(metrics_raw.get("business_timezone", "Asia/Kolkata")),

        reporting_currency=str(metrics_raw.get("reporting_currency", "INR")),

        metrics=metrics,

        dimensions=dimensions,

        terms=terms,

    )


 