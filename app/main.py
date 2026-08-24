from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.service import process_command
from app.store import get_rules


app = FastAPI(
    title="Natural Language Action Agent",
    description="A local LLM-powered smart-facility action service.",
    version="1.0.0",
)


class CommandRequest(BaseModel):
    text: str


@app.get("/")
def root():
    """
    Basic health/status endpoint.
    """

    return {
        "success": True,
        "message": "Natural Language Action Agent is running.",
    }


@app.post("/command")
def command(request: CommandRequest):
    """
    Convert a natural-language command into a validated action
    and execute it.
    """

    text = request.text.strip()

    if not text:
        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "error": "EMPTY_COMMAND",
                "message": "Command text cannot be empty.",
            },
        )

    try:
        result = process_command(text)

        return {
            "success": True,
            "input": text,
            **result,
        }

    except ValueError as exc:
        return JSONResponse(
            status_code=422,
            content={
                "success": False,
                "error": "VALIDATION_ERROR",
                "message": str(exc),
            },
        )

    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": "INTERNAL_ERROR",
                "message": "An unexpected error occurred while processing the command.",
                "detail": str(exc),
            },
        )


@app.get("/rules")
def rules(device_id: str | None = None):
    """
    Return all stored alert rules.

    If device_id is supplied, only rules for that device are returned.
    """

    stored_rules = get_rules(device_id)

    return {
        "success": True,
        "count": len(stored_rules),
        "rules": stored_rules,
    }


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(
    request,
    exc: RequestValidationError,
):
    """
    Return a cleaner JSON response for malformed API requests.
    """

    return JSONResponse(
        status_code=422,
        content={
            "success": False,
            "error": "REQUEST_VALIDATION_ERROR",
            "message": "Invalid request format.",
            "details": exc.errors(),
        },
    )