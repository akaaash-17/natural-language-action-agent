from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field


class CreateAlertRule(BaseModel):
    type: Literal["CREATE_ALERT_RULE"] = "CREATE_ALERT_RULE"
    device_id: str
    metric: str
    condition: Literal["ABOVE", "BELOW", "EQUALS"]
    threshold: float
    duration_minutes: float
    notify_via: list[Literal["EMAIL", "SMS", "PUSH"]]


class QueryStatus(BaseModel):
    type: Literal["QUERY_STATUS"] = "QUERY_STATUS"
    device_id: str
    metric: str | None = None


class ListRules(BaseModel):
    type: Literal["LIST_RULES"] = "LIST_RULES"
    device_id: str | None = None


class Unsupported(BaseModel):
    type: Literal["UNSUPPORTED"] = "UNSUPPORTED"
    reason: str


Action = Annotated[
    Union[
        CreateAlertRule,
        QueryStatus,
        ListRules,
        Unsupported,
    ],
    Field(discriminator="type"),
]