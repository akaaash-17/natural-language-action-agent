from dataclasses import dataclass
from typing import Literal

from app.registry import ASSET_REGISTRY


ResolutionStatus = Literal["EXACT", "AMBIGUOUS", "UNKNOWN"]


@dataclass
class ParameterResolution:
    """
    Result of resolving a user-requested parameter against
    an asset's registered sensors and parameters.
    """

    status: ResolutionStatus
    asset_id: str
    requested_parameter: str
    matches: list[dict]


def resolve_parameter(
    asset_id: str,
    parameter: str,
) -> ParameterResolution:
    """
    Resolve a parameter against the sensors belonging to an asset.

    Returns:
        EXACT:
            Exactly one registered parameter matches.

        AMBIGUOUS:
            Multiple parameters semantically match the request.

        UNKNOWN:
            No registered parameter matches.
    """

    asset = ASSET_REGISTRY.get(asset_id)

    if asset is None:
        return ParameterResolution(
            status="UNKNOWN",
            asset_id=asset_id,
            requested_parameter=parameter,
            matches=[],
        )

    requested = parameter.strip().lower()

    matches = []

    for sensor_id, sensor in asset["sensors"].items():
        for registered_parameter in sensor["parameters"]:
            parameter_lower = registered_parameter.lower()

            if (
                requested == parameter_lower
                or requested == sensor_id.lower()
                or requested == sensor_id.replace("_", " ").lower()
                or requested == registered_parameter.replace("_", " ").lower()
            ):
                matches.append(
                    {
                        "sensor": sensor_id,
                        "parameter": registered_parameter,
                    }
                )

    if len(matches) == 1:
        status: ResolutionStatus = "EXACT"
    elif len(matches) > 1:
        status = "AMBIGUOUS"
    else:
        status = "UNKNOWN"

    return ParameterResolution(
        status=status,
        asset_id=asset_id,
        requested_parameter=parameter,
        matches=matches,
    )


def find_parameters_by_concept(
    asset_id: str,
    concept: str,
) -> ParameterResolution:
    """
    Resolve a broad parameter concept such as 'temperature'
    against the parameters available on an asset.

    Example:

        tipper-101 + temperature

    can produce:

        hydraulic_temperature
        engine_temperature
        oil_temperature
    """

    asset = ASSET_REGISTRY.get(asset_id)

    if asset is None:
        return ParameterResolution(
            status="UNKNOWN",
            asset_id=asset_id,
            requested_parameter=concept,
            matches=[],
        )

    requested = concept.strip().lower()

    matches = []

    for sensor_id, sensor in asset["sensors"].items():
        for registered_parameter in sensor["parameters"]:
            parameter_lower = registered_parameter.lower()

            # Exact match first.
            if requested == parameter_lower:
                matches.append(
                    {
                        "sensor": sensor_id,
                        "parameter": registered_parameter,
                    }
                )
                continue

            # Concept match:
            # temperature -> hydraulic_temperature
            # temperature -> engine_temperature
            # pressure -> hydraulic_pressure
            if requested in parameter_lower:
                matches.append(
                    {
                        "sensor": sensor_id,
                        "parameter": registered_parameter,
                    }
                )

    # Remove duplicates while preserving order.
    unique_matches = []
    seen = set()

    for match in matches:
        key = (match["sensor"], match["parameter"])

        if key not in seen:
            seen.add(key)
            unique_matches.append(match)

    if len(unique_matches) == 1:
        status: ResolutionStatus = "EXACT"
    elif len(unique_matches) > 1:
        status = "AMBIGUOUS"
    else:
        status = "UNKNOWN"

    return ParameterResolution(
        status=status,
        asset_id=asset_id,
        requested_parameter=concept,
        matches=unique_matches,
    )


def format_resolution_message(
    resolution: ParameterResolution,
) -> str:
    """
    Convert a resolution result into a user-friendly message.
    """

    if resolution.status == "EXACT":
        match = resolution.matches[0]

        return (
            f"Resolved '{resolution.requested_parameter}' to "
            f"parameter '{match['parameter']}' on sensor "
            f"'{match['sensor']}' of asset '{resolution.asset_id}'."
        )

    if resolution.status == "AMBIGUOUS":
        options = ", ".join(
            match["parameter"]
            for match in resolution.matches
        )

        return (
            f"Multiple parameters match "
            f"'{resolution.requested_parameter}' on "
            f"'{resolution.asset_id}': {options}. "
            "Please specify which parameter you want."
        )

    return (
        f"Parameter '{resolution.requested_parameter}' "
        f"is not registered for asset '{resolution.asset_id}'."
    )