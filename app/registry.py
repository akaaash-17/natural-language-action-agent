ASSET_REGISTRY = {
    "warehouse-3": {
        "sensors": {
            "environment": {
                "parameters": ["temperature", "humidity"]
            }
        }
    },
    "cold-storage-1": {
        "sensors": {
            "environment": {
                "parameters": ["temperature", "humidity"]
            }
        }
    },
    "front-gate": {
        "sensors": {
            "security": {
                "parameters": ["camera_status", "occupancy"]
            }
        }
    },
    "server-room-1": {
        "sensors": {
            "environment": {
                "parameters": ["temperature", "humidity"]
            }
        }
    },
    "production-floor-1": {
        "sensors": {
            "environment": {
                "parameters": ["temperature", "humidity"]
            },
            "occupancy": {
                "parameters": ["occupancy"]
            }
        }
    },
    "loading-bay-1": {
        "sensors": {
            "environment": {
                "parameters": ["temperature"]
            },
            "security": {
                "parameters": ["occupancy"]
            }
        }
    },

    # Real-world style assets for the upgraded resolver.
    "tipper-101": {
        "sensors": {
            "hydraulic": {
                "parameters": [
                    "hydraulic_temperature",
                    "hydraulic_pressure",
                ]
            },
            "engine": {
                "parameters": [
                    "engine_temperature",
                    "oil_temperature",
                    "engine_pressure",
                ]
            },
        }
    },
    "concrete-mixer-101": {
        "sensors": {
            "engine": {
                "parameters": [
                    "engine_temperature",
                    "oil_temperature",
                ]
            },
            "hydraulic": {
                "parameters": [
                    "hydraulic_temperature",
                    "hydraulic_pressure",
                ]
            },
        }
    },
}


def build_device_registry() -> dict:
    """
    Build the legacy device -> metrics registry from the
    hierarchical asset registry.

    This keeps the existing validation and execution layer
    compatible while the system transitions to the new model.
    """

    registry = {}

    for asset_id, asset in ASSET_REGISTRY.items():
        metrics = []

        for sensor in asset["sensors"].values():
            metrics.extend(sensor["parameters"])

        registry[asset_id] = {
            "metrics": sorted(set(metrics))
        }

    return registry


# Backwards-compatible registry used by the existing validator.
DEVICE_REGISTRY = build_device_registry()