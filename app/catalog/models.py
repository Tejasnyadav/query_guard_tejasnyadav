from datetime import date, datetime

from typing import Any


 

from pydantic import BaseModel, Field



 

class MetricDefinition(BaseModel):

    metric_id: str

    label: str

    description: str

    expression: str

    source_view: str

    required_filter: str | None = None

    time_column: str

    unit: str



 

class DimensionDefinition(BaseModel):

    dimension_id: str

    source_view: str

    column: str

    description: str

    allowed_values: list[str] = Field(default_factory=list)



 

class BusinessTermDefinition(BaseModel):

    term: str

    definition: str | None = None

    explanation: str | None = None

    limitation: str | None = None

    clarification_required: bool = False

    choices: list[str] = Field(default_factory=list)



 

class SemanticCatalog(BaseModel):

    version: int

    business_timezone: str

    reporting_currency: str

    metrics: dict[str, MetricDefinition]

    dimensions: dict[str, DimensionDefinition]

    terms: dict[str, BusinessTermDefinition]


 

    def compact_for_prompt(self) -> dict[str, Any]:

        return {

            "business_timezone": self.business_timezone,

            "reporting_currency": self.reporting_currency,

            "metrics": {

                key: {

                    "label": value.label,

                    "description": value.description,

                    "source_view": value.source_view,

                    "required_filter": value.required_filter,

                    "time_column": value.time_column,

                    "unit": value.unit,

                }

                for key, value in self.metrics.items()

            },

            "dimensions": {

                key: {

                    "description": value.description,

                    "source_view": value.source_view,

                    "column": value.column,

                    "allowed_values": value.allowed_values,

                }

                for key, value in self.dimensions.items()

            },

            "business_terms": {

                key: value.model_dump(exclude_none=True)

                for key, value in self.terms.items()

            },

        }



 

class ColumnDefinition(BaseModel):

    name: str

    data_type: str

    ordinal_position: int



 

class TableDefinition(BaseModel):

    qualified_name: str

    columns: list[ColumnDefinition]



 

class DatasetMetadata(BaseModel):

    dataset_name: str

    dataset_version: str

    as_of_date: date

    business_timezone: str

    reporting_currency: str

    generated_at: datetime | None = None



 

class SchemaSnapshot(BaseModel):

    dataset: DatasetMetadata

    tables: list[TableDefinition]


 